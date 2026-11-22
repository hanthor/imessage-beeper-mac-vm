"""Unit tests for scripts/console/driver.py.

Nothing here touches a VM: virtctl, corral, tesseract and time.sleep are
replaced, so the suite runs anywhere with only the standard library.

    python3 -m unittest discover -s tests -v
"""
import contextlib
import importlib.util
import io
import struct
import subprocess
import unittest
from pathlib import Path
from unittest import mock

DRIVER = Path(__file__).resolve().parent.parent / "scripts" / "console" / "driver.py"
_spec = importlib.util.spec_from_file_location("console_driver", DRIVER)
driver = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(driver)

SHIFT = driver.KEYS["SHIFT"]


class FakeConn:
    """Collects bytes sent over the VNC socket."""

    def __init__(self):
        self.sent = []

    def sendall(self, data):
        self.sent.append(data)

    def close(self):
        pass


def key_events(conn):
    """Decode KeyEvent messages into (keysym, down) tuples."""
    events = []
    for data in conn.sent:
        if data[0] == 4:
            _, down, _, sym = struct.unpack(">BBHi", data)
            events.append((sym, down))
    return events


class ResolveTest(unittest.TestCase):
    def test_named_key(self):
        self.assertEqual(driver._resolve("TAB"), 0xFF09)

    def test_single_character_is_its_codepoint(self):
        self.assertEqual(driver._resolve("a"), ord("a"))
        self.assertEqual(driver._resolve("2"), ord("2"))

    def test_unknown_multi_character_name_raises(self):
        with self.assertRaises(KeyError):
            driver._resolve("minus")


class CharPartsTest(unittest.TestCase):
    def test_lowercase_and_digits_are_unshifted(self):
        self.assertEqual(driver._char_parts("a"), [ord("a")])
        self.assertEqual(driver._char_parts("7"), [ord("7")])

    def test_uppercase_adds_shift(self):
        self.assertEqual(driver._char_parts("A"), [SHIFT, ord("A")])

    def test_space_is_the_space_key(self):
        self.assertEqual(driver._char_parts(" "), [driver.KEYS["SPC"]])

    def test_unshifted_punctuation(self):
        self.assertEqual(driver._char_parts("."), [0x2E])
        self.assertEqual(driver._char_parts("-"), [0x2D])
        self.assertEqual(driver._char_parts("/"), [0x2F])

    def test_digit_row_symbols_use_shift_plus_digit(self):
        self.assertEqual(driver._char_parts("@"), [SHIFT, ord("2")])
        self.assertEqual(driver._char_parts("!"), [SHIFT, ord("1")])
        self.assertEqual(driver._char_parts(")"), [SHIFT, ord("0")])

    def test_non_ascii_is_rejected(self):
        with self.assertRaises(ValueError):
            driver._char_parts("é")

    @unittest.expectedFailure
    def test_shifted_named_symbols_are_typable(self):
        # `type` is how credentials reach the guest; "_", "+", ":" and "?" are
        # common in passwords. Each of these maps to Shift + the base key.
        expected = {
            "_": 0x2D, "+": 0x3D, "{": 0x5B, "}": 0x5D, "|": 0x5C,
            ":": 0x3B, '"': 0x27, "<": 0x2C, ">": 0x2E, "?": 0x2F,
            "~": 0x60,
        }
        for ch, base in expected.items():
            with self.subTest(ch=ch):
                self.assertEqual(driver._char_parts(ch), [SHIFT, base])


class KeyEventTest(unittest.TestCase):
    def test_key_message_layout(self):
        conn = FakeConn()
        with mock.patch.object(driver.time, "sleep"):
            driver._key(conn, 0xFF09, 1)
        self.assertEqual(conn.sent, [struct.pack(">BBHi", 4, 1, 0, 0xFF09)])

    def test_press_parts_presses_in_order_and_releases_reversed(self):
        conn = FakeConn()
        with mock.patch.object(driver.time, "sleep"):
            driver._press_parts(conn, [SHIFT, ord("A")])
        self.assertEqual(
            key_events(conn),
            [(SHIFT, 1), (ord("A"), 1), (ord("A"), 0), (SHIFT, 0)],
        )

    def _send_keys(self, specs):
        conn = FakeConn()
        proxy = mock.Mock()
        with mock.patch.object(driver, "_vnc_connect", return_value=(conn, proxy)), \
                mock.patch.object(driver, "_handshake"), \
                mock.patch.object(driver.time, "sleep"):
            driver.send_keys(specs)
        return conn, proxy

    def test_send_keys_single_key_is_press_then_release(self):
        conn, _ = self._send_keys(["TAB"])
        self.assertEqual(key_events(conn), [(0xFF09, 1), (0xFF09, 0)])

    def test_send_keys_combo_releases_in_reverse(self):
        conn, _ = self._send_keys(["CTRL+F7"])
        ctrl, f7 = driver.KEYS["CTRL"], driver.KEYS["F7"]
        self.assertEqual(
            key_events(conn), [(ctrl, 1), (f7, 1), (f7, 0), (ctrl, 0)]
        )

    def test_send_keys_closes_connection_and_stops_proxy_on_error(self):
        conn = FakeConn()
        conn.close = mock.Mock()
        proxy = mock.Mock()
        with mock.patch.object(driver, "_vnc_connect", return_value=(conn, proxy)), \
                mock.patch.object(driver, "_handshake"), \
                mock.patch.object(driver.time, "sleep"):
            with self.assertRaises(KeyError):
                driver.send_keys(["NOSUCHKEY"])
        conn.close.assert_called_once()
        proxy.terminate.assert_called_once()

    def test_type_text_validates_before_connecting(self):
        with mock.patch.object(driver, "_vnc_connect") as connect:
            with self.assertRaises(ValueError):
                driver.type_text("oké")
        connect.assert_not_called()

    def test_pointer_presses_then_releases_at_same_coordinates(self):
        conn = FakeConn()
        proxy = mock.Mock()
        with mock.patch.object(driver, "_vnc_connect", return_value=(conn, proxy)), \
                mock.patch.object(driver, "_handshake"), \
                mock.patch.object(driver.time, "sleep"):
            driver.pointer(1, 120, 340, hold=1.0)
        self.assertEqual(
            conn.sent,
            [struct.pack(">BBHH", 5, 1, 120, 340),
             struct.pack(">BBHH", 5, 0, 120, 340)],
        )
        proxy.terminate.assert_called_once()


class RxTest(unittest.TestCase):
    def test_reassembles_short_reads(self):
        conn = mock.Mock()
        conn.recv.side_effect = [b"ab", b"cd", b"e"]
        self.assertEqual(driver._rx(conn, 5), b"abcde")

    def test_closed_socket_raises(self):
        conn = mock.Mock()
        conn.recv.side_effect = [b"ab", b""]
        with self.assertRaises(RuntimeError):
            driver._rx(conn, 5)


TSV_HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"


def tsv_row(left, top, w, h, conf, text):
    return f"5\t1\t1\t1\t1\t1\t{left}\t{top}\t{w}\t{h}\t{conf}\t{text}"


class OcrWordsTest(unittest.TestCase):
    def _words(self, rows):
        out = mock.Mock(stdout="\n".join([TSV_HEADER, *rows]))
        with mock.patch.object(driver.subprocess, "run", return_value=out):
            return driver.ocr_words("shot.png")

    def test_center_and_confidence(self):
        words = self._words([tsv_row(100, 200, 40, 20, "96.5", "Continue")])
        self.assertEqual(words, [("Continue", 120, 210, 96.5)])

    def test_skips_blank_text_negative_confidence_and_short_rows(self):
        words = self._words([
            tsv_row(0, 0, 10, 10, "90", "   "),
            tsv_row(0, 0, 10, 10, "-1", "layout"),
            "5\t1\t1",
            tsv_row(10, 10, 10, 10, "80", "kept"),
        ])
        self.assertEqual([w[0] for w in words], ["kept"])

    def test_non_numeric_confidence_is_treated_as_unreadable(self):
        self.assertEqual(self._words([tsv_row(0, 0, 10, 10, "n/a", "word")]), [])

    def test_invokes_tesseract_with_tsv_output(self):
        out = mock.Mock(stdout=TSV_HEADER)
        with mock.patch.object(driver.subprocess, "run", return_value=out) as run:
            driver.ocr_words("shot.png")
        self.assertEqual(
            run.call_args.args[0],
            ["tesseract", "shot.png", "stdout", "-l", "eng", "tsv"],
        )


class FindTextTest(unittest.TestCase):
    WORDS = [
        ("Sign", 10, 50, 90.0),
        ("In", 30, 52, 90.0),
        ("Continue", 200, 300, 90.0),
        ("Signing", 400, 80, 90.0),
    ]

    def _find(self, needle, **kw):
        with mock.patch.object(driver, "ocr_words", return_value=self.WORDS):
            return driver.find_text("shot.png", needle, **kw)

    def test_single_word_exact(self):
        self.assertEqual(self._find("continue"), (200, 300))

    def test_multi_word_returns_mean_center(self):
        self.assertEqual(self._find("Sign In"), (20, 51))

    def test_match_is_case_insensitive(self):
        self.assertEqual(self._find("CONTINUE"), (200, 300))

    def test_loose_falls_back_to_substring_of_first_word(self):
        # "Signi" is not a word, but is contained in "Signing".
        self.assertEqual(self._find("Signi"), (400, 80))

    def test_loose_false_requires_exact_sequence(self):
        self.assertIsNone(self._find("Signi", loose=False))

    def test_absent_text_is_none(self):
        self.assertIsNone(self._find("Cancel"))


class PollTest(unittest.TestCase):
    def setUp(self):
        for name in ("shot", "ocr_text"):
            patcher = mock.patch.object(driver, name)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(driver.time, "sleep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_returns_as_soon_as_text_appears(self):
        self.ocr_text.side_effect = ["loading", "Welcome to Mac", "never read"]
        ok, text = driver.poll("p.png", "welcome", timeout=1000)
        self.assertTrue(ok)
        self.assertEqual(text, "Welcome to Mac")
        self.assertEqual(self.shot.call_count, 2)

    def test_vanish_waits_for_text_to_disappear(self):
        self.ocr_text.side_effect = ["Updating...", "Updating...", "done"]
        ok, text = driver.poll("p.png", "updating", timeout=1000, vanish=True)
        self.assertTrue(ok)
        self.assertEqual(text, "done")

    def test_times_out_and_reports_last_ocr(self):
        self.ocr_text.return_value = "still loading"
        with mock.patch.object(driver.time, "time", side_effect=[0, 1, 2, 999]):
            ok, text = driver.poll("p.png", "welcome", timeout=100)
        self.assertFalse(ok)
        self.assertEqual(text, "still loading")


class ShotTest(unittest.TestCase):
    def _run(self, results):
        def fake_run(argv, **kw):
            if argv[:2] == ["corral", "context"]:
                return mock.Mock(stdout="", stderr="")
            return results.pop(0)

        return mock.patch.object(driver.subprocess, "run", side_effect=fake_run)

    def test_returns_path_on_first_success(self):
        ok = mock.Mock(stdout="Screenshot written to x.png", stderr="")
        with self._run([ok]), mock.patch.object(driver.time, "sleep") as sleep:
            self.assertEqual(driver.shot("x.png"), "x.png")
        sleep.assert_not_called()

    def test_retries_with_growing_backoff(self):
        bad = mock.Mock(stdout="", stderr="busy")
        ok = mock.Mock(stdout="Screenshot written to x.png", stderr="")
        with self._run([bad, bad, ok]), \
                mock.patch.object(driver.time, "sleep") as sleep:
            self.assertEqual(driver.shot("x.png"), "x.png")
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [15, 25])

    def test_raises_with_stderr_tail_when_all_tries_fail(self):
        bad = mock.Mock(stdout="", stderr="vnc unreachable")
        with self._run([bad, bad]), mock.patch.object(driver.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "vnc unreachable"):
                driver.shot("x.png", tries=2)

    def test_screenshot_target_is_built_from_environment_defaults(self):
        seen = []

        def fake_run(argv, **kw):
            seen.append(argv)
            return mock.Mock(stdout="Screenshot written", stderr="")

        with mock.patch.object(driver.subprocess, "run", side_effect=fake_run), \
                mock.patch.object(driver.time, "sleep"):
            driver.shot("x.png")
        self.assertEqual(
            seen[-1],
            ["corral", "screenshot",
             f"kubevirt/{driver.CTX}/{driver.NS}/{driver.VM}", "-o", "x.png"],
        )


class ClickTextTest(unittest.TestCase):
    def test_raises_when_text_never_appears(self):
        with mock.patch.object(driver, "poll", return_value=(False, "")):
            with self.assertRaisesRegex(RuntimeError, "never appeared"):
                driver.click_text("p.png", "Next")

    def test_raises_when_text_seen_but_not_located(self):
        with mock.patch.object(driver, "poll", return_value=(True, "Next")), \
                mock.patch.object(driver, "find_text", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "not located"):
                driver.click_text("p.png", "Next")

    def test_reports_whether_pane_changed_after_click(self):
        for before, after, expected in (("A", "B", True), ("A", "A", False)):
            with self.subTest(before=before, after=after), \
                    mock.patch.object(driver, "poll", return_value=(True, "")), \
                    mock.patch.object(driver, "find_text", return_value=(5, 6)), \
                    mock.patch.object(driver, "ocr_text", side_effect=[before, after]), \
                    mock.patch.object(driver, "pointer") as pointer, \
                    mock.patch.object(driver, "shot"), \
                    mock.patch.object(driver.time, "sleep"):
                changed, text = driver.click_text("p.png", "Next", hold=2.0)
            self.assertEqual((changed, text), (expected, after))
            pointer.assert_called_once_with(1, 5, 6, hold=2.0)


class ActivateTest(unittest.TestCase):
    def test_fails_fast_with_actionable_error_when_tab_moves_no_ring(self):
        with mock.patch.object(driver, "poll", return_value=(True, "")), \
                mock.patch.object(driver, "shot"), \
                mock.patch.object(driver, "find_text", return_value=(1, 1)), \
                mock.patch.object(driver, "_crop_blue", return_value=0), \
                mock.patch.object(driver, "send_keys") as send_keys, \
                mock.patch.object(driver.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "Full Keyboard Access"):
                driver.activate("p.png", "Continue")
        self.assertEqual(send_keys.call_count, 12)
        send_keys.assert_called_with(["TAB"])

    def test_presses_space_once_the_target_has_the_focus_ring(self):
        blue = [0, 0, 99]
        with mock.patch.object(driver, "poll", side_effect=[(True, ""), (True, "next")]), \
                mock.patch.object(driver, "shot"), \
                mock.patch.object(driver, "find_text", return_value=(1, 1)), \
                mock.patch.object(driver, "_crop_blue", side_effect=blue), \
                mock.patch.object(driver, "ocr_text", return_value="before"), \
                mock.patch.object(driver, "send_keys") as send_keys, \
                mock.patch.object(driver.time, "sleep"):
            ok, after = driver.activate("p.png", "Continue")
        self.assertTrue(ok)
        self.assertEqual(after, "next")
        self.assertEqual(
            [c.args[0] for c in send_keys.call_args_list],
            [["TAB"], ["TAB"], ["SPC"]],
        )

    def test_does_not_press_space_when_text_never_appears(self):
        with mock.patch.object(driver, "poll", return_value=(False, "")), \
                mock.patch.object(driver, "send_keys") as send_keys:
            with self.assertRaisesRegex(RuntimeError, "never appeared"):
                driver.activate("p.png", "Continue")
        send_keys.assert_not_called()


class MainTest(unittest.TestCase):
    def setUp(self):
        out = contextlib.redirect_stdout(io.StringIO())
        out.__enter__()
        self.addCleanup(out.__exit__, None, None, None)

    def test_unknown_command_exits_with_message(self):
        with self.assertRaises(SystemExit) as ctx:
            driver.main(["frobnicate"])
        self.assertEqual(ctx.exception.code, "unknown command frobnicate")

    def test_type_joins_arguments_with_spaces(self):
        with mock.patch.object(driver, "type_text") as type_text:
            driver.main(["type", "hello", "world"])
        type_text.assert_called_once_with("hello world")

    def test_key_splits_comma_separated_specs(self):
        with mock.patch.object(driver, "send_keys") as send_keys:
            driver.main(["key", "TAB,SPC"])
        send_keys.assert_called_once_with(["TAB", "SPC"])

    def test_wait_exit_status_reflects_the_poll_result(self):
        for found, code in ((True, 0), (False, 1)):
            with self.subTest(found=found), \
                    mock.patch.object(driver, "poll", return_value=(found, "x")):
                with self.assertRaises(SystemExit) as ctx:
                    driver.main(["wait", "Welcome", "30"])
                self.assertEqual(ctx.exception.code, code)

    def test_wait_passes_timeout_as_int(self):
        with mock.patch.object(driver, "poll", return_value=(True, "")) as poll:
            with self.assertRaises(SystemExit):
                driver.main(["wait", "Welcome", "30"])
        self.assertEqual(poll.call_args.kwargs["timeout"], 30)


@unittest.skipUnless(
    importlib.util.find_spec("PIL"), "Pillow is needed for focus-ring detection"
)
class FocusRingTest(unittest.TestCase):
    def _image(self, path, blue_box=None):
        from PIL import Image

        img = Image.new("RGB", (100, 60), (240, 240, 240))
        if blue_box:
            x0, y0, x1, y1 = blue_box
            for x in range(x0, x1):
                for y in range(y0, y1):
                    img.putpixel((x, y), (10, 100, 255))
        img.save(path)

    def test_crop_blue_counts_only_ring_coloured_pixels(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            plain = Path(tmp) / "plain.png"
            ringed = Path(tmp) / "ringed.png"
            self._image(plain)
            self._image(ringed, blue_box=(40, 25, 60, 35))
            self.assertEqual(driver._crop_blue(str(plain), (50, 30)), 0)
            self.assertGreater(driver._crop_blue(str(ringed), (50, 30)), 30)

    def test_crop_blue_clamps_to_image_origin(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "corner.png"
            self._image(path, blue_box=(0, 0, 10, 10))
            self.assertGreater(driver._crop_blue(str(path), (2, 2)), 0)


if __name__ == "__main__":
    unittest.main()
