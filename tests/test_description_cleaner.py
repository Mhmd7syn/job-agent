import pytest
from scrapers.common import filter_linkedin_social_noise


def test_filter_linkedin_social_action_buttons():
    raw_text = (
        "We are hiring a Senior Computer Vision Engineer to join our team in Cairo.\n"
        "Like\n"
        "Comment\n"
        "Repost\n"
        "Send\n"
        "• 5+ years experience in PyTorch and OpenCV\n"
        "• Experience with model deployment on edge devices\n"
        "Like Comment Repost Send\n"
    )
    cleaned = filter_linkedin_social_noise(raw_text)

    assert "Senior Computer Vision Engineer" in cleaned
    assert "• 5+ years experience in PyTorch and OpenCV" in cleaned
    assert "• Experience with model deployment on edge devices" in cleaned

    # Noise must be purged
    assert "Like Comment Repost Send" not in cleaned
    lines = [l.strip() for l in cleaned.splitlines() if l.strip()]
    assert "Like" not in lines
    assert "Comment" not in lines
    assert "Repost" not in lines
    assert "Send" not in lines


def test_filter_linkedin_reaction_and_comment_counts():
    raw_text = (
        "Company Overview:\n"
        "We build cutting-edge generative AI systems.\n"
        "245 reactions • 38 comments\n"
        "1,450 comments\n"
        "See all 45 comments\n"
        "Requirements:\n"
        "• Strong background in LLMs and Python\n"
    )
    cleaned = filter_linkedin_social_noise(raw_text)

    assert "We build cutting-edge generative AI systems." in cleaned
    assert "• Strong background in LLMs and Python" in cleaned
    assert "245 reactions" not in cleaned
    assert "1,450 comments" not in cleaned
    assert "See all 45 comments" not in cleaned


def test_filter_linkedin_followers_and_follow_buttons():
    raw_text = (
        "Acme AI Inc.\n"
        "25,400 followers\n"
        "+ Follow\n"
        "Following\n"
        "Connect\n"
        "Role: Data Analyst\n"
        "Location: Remote / Egypt\n"
    )
    cleaned = filter_linkedin_social_noise(raw_text)

    assert "Acme AI Inc." in cleaned
    assert "Role: Data Analyst" in cleaned
    assert "Location: Remote / Egypt" in cleaned

    assert "25,400 followers" not in cleaned
    assert "+ Follow" not in cleaned
    lines = [l.strip() for l in cleaned.splitlines()]
    assert "Following" not in lines
    assert "Connect" not in lines


def test_filter_linkedin_engagement_headers():
    raw_text = (
        "Ahmed Ali likes this\n"
        "Sarah Mostafa commented on this\n"
        "Khaled Omar reposted this\n"
        "Hiring Announcement:\n"
        "We are looking for an ML Ops Specialist.\n"
    )
    cleaned = filter_linkedin_social_noise(raw_text)

    assert "Hiring Announcement:" in cleaned
    assert "We are looking for an ML Ops Specialist." in cleaned
    assert "Ahmed Ali likes this" not in cleaned
    assert "Sarah Mostafa commented on this" not in cleaned
    assert "Khaled Omar reposted this" not in cleaned


def test_filter_linkedin_relative_timestamp_and_menu_artifacts():
    raw_text = (
        "2w • Edited •\n"
        "3d • Visible to public\n"
        "Open control menu\n"
        "Responsibilities:\n"
        "• Build and maintain automated pipelines\n"
    )
    cleaned = filter_linkedin_social_noise(raw_text)

    assert "Responsibilities:" in cleaned
    assert "• Build and maintain automated pipelines" in cleaned
    assert "2w • Edited •" not in cleaned
    assert "3d • Visible to public" not in cleaned
    assert "Open control menu" not in cleaned


def test_filter_linkedin_edge_cases():
    assert filter_linkedin_social_noise("") == ""
    assert filter_linkedin_social_noise(None) == ""
    assert filter_linkedin_social_noise("   \n\n   ") == ""
