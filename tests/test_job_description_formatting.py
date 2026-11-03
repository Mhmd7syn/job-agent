import json
import unittest

from scrapers.common import extract_json_ld_job, html_to_text


def _job_html(description: str) -> str:
    payload = {'@type': 'JobPosting', 'title': 'Engineer', 'description': description}
    return f'<script type="application/ld+json">{json.dumps(payload)}</script>'


class TestJobDescriptionFormatting(unittest.TestCase):
    def test_paragraphs_breaks_and_list_items_keep_structure(self):
        html = _job_html(
            '<p>Intro</p><p>Second</p><ul><li>One</li><li>Two</li></ul>Line<br>after'
        )

        result = extract_json_ld_job(html)

        self.assertEqual(
            result['description'],
            'Intro\n\nSecond\n\n• One\n• Two\n\nLine\nafter',
        )

    def test_nested_blocks_in_list_items_keep_bullets_attached(self):
        html = _job_html(
            '<ul><li><p>Requirement 1</p></li><li><div>Requirement 2</div></li></ul>'
        )

        result = extract_json_ld_job(html)

        self.assertEqual(
            result['description'],
            '• Requirement 1\n• Requirement 2',
        )

    def test_multiple_paragraphs_in_single_list_item(self):
        html = _job_html(
            '<ul><li><p>Primary responsibility</p><p>Secondary details</p></li></ul>'
        )

        result = extract_json_ld_job(html)

        self.assertEqual(
            result['description'],
            '• Primary responsibility\nSecondary details',
        )

    def test_empty_and_none_inputs_handled_safely(self):
        self.assertEqual(html_to_text(None), '')
        self.assertEqual(html_to_text(''), '')
        self.assertEqual(html_to_text('   '), '')


if __name__ == '__main__':
    unittest.main()
