from __future__ import annotations

import unittest

from app.omnivoice.workspaces.expressive import (
    PAUSE_DIRECTIVE,
    ExpressiveCapabilities,
    PronunciationRule,
    compile_expressive_text,
)


class ExpressiveTextTests(unittest.TestCase):
    def test_compiles_vietnamese_rate_emotion_pause_and_pronunciation(self) -> None:
        rule = PronunciationRule.create("OpenAI", "Ô-pần Ây-ai", language="vi")
        result = compile_expressive_text(
            '[emotion vui][rate 0.9]OpenAI bắt đầu.[/rate][/emotion] [pause 650ms]',
            language="vi",
            pronunciation_rules=(rule,),
        )

        speech = result.directives[0]
        self.assertEqual(speech.display_text, "OpenAI bắt đầu.")
        self.assertEqual(speech.spoken_text, "Ô-pần Ây-ai bắt đầu.")
        self.assertEqual(speech.rate, 0.9)
        self.assertIn("vui", speech.instruction)
        self.assertEqual(result.directives[1].kind, PAUSE_DIRECTIVE)
        self.assertEqual(result.directives[1].pause_ms, 650)
        self.assertFalse(result.issues)

    def test_keeps_english_display_text_when_explicit_pronunciation_changes_speech(self) -> None:
        result = compile_expressive_text(
            '[emphasis][pronounce "Doctor Smith"]Dr. Smith[/pronounce][/emphasis]',
            language="en",
        )

        directive = result.directives[0]
        self.assertEqual(directive.display_text, "Dr. Smith")
        self.assertEqual(directive.spoken_text, "Doctor Smith")
        self.assertTrue(directive.emphasis)
        self.assertIn("Emphasize", directive.instruction)

    def test_chinese_spell_and_phoneme_have_deterministic_fallbacks(self) -> None:
        result = compile_expressive_text(
            '[spell]AI[/spell] [phoneme "ni3 hao3"]你好[/phoneme]',
            language="zh",
            capabilities=ExpressiveCapabilities(phoneme=False),
        )

        self.assertEqual(result.directives[0].spoken_text, "A I")
        self.assertEqual(result.directives[1].spoken_text, "你好")
        self.assertIn("phoneme-degraded", {issue.code for issue in result.issues})

    def test_reports_invalid_or_unclosed_markup_without_dropping_text(self) -> None:
        result = compile_expressive_text("Xin [rate nhanh]chào bạn")

        codes = {issue.code for issue in result.issues}
        self.assertIn("invalid-rate", codes)
        self.assertIn("unclosed-tag", codes)
        self.assertEqual(" ".join(item.display_text for item in result.directives), "Xin chào bạn")

    def test_preserves_supported_omnivoice_non_verbal_events(self) -> None:
        result = compile_expressive_text("Xin chào [laughter]")

        self.assertEqual(result.directives[-1].spoken_text, "[laughter]")
        self.assertNotIn("unknown-tag", {issue.code for issue in result.issues})

    def test_rejects_out_of_range_rate_and_pause_instead_of_clamping(self) -> None:
        result = compile_expressive_text("[rate 9]Nhanh[/rate] [pause 20s]")

        error_codes = {issue.code for issue in result.issues if issue.severity == "error"}
        self.assertEqual(error_codes, {"invalid-rate", "invalid-pause"})
        self.assertEqual(result.directives[0].rate, 1.0)
        self.assertFalse(any(item.kind == PAUSE_DIRECTIVE for item in result.directives))


if __name__ == "__main__":
    unittest.main()
