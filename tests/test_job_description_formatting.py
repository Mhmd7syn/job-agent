import json
import unittest

from scrapers.common import extract_json_ld_job


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


if __name__ == '__main__':
    unittest.main()
