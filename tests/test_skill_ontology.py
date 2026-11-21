import pytest
from core.skill_ontology import SkillOntology, ontology

def test_canonical_mappings():
    # Cloud
    assert ontology.get_canonical_skill("gcp") == ontology.get_canonical_skill("google cloud")
    assert ontology.get_canonical_skill("google cloud platform") == ontology.get_canonical_skill("gcp")
    assert ontology.are_synonyms("gcp", "google cloud")
    assert ontology.are_synonyms("aws", "amazon web services")
    assert ontology.are_synonyms("k8s", "kubernetes")

    # Vision
    assert ontology.are_synonyms("cv", "computer vision")
    assert ontology.are_synonyms("u-net", "unet")
    assert ontology.are_synonyms("cnn", "3d cnn")

    # NLP
    assert ontology.are_synonyms("nlp", "natural language processing")
    assert ontology.are_synonyms("genai", "generative ai")
    assert ontology.are_synonyms("transformers", "transformer")

    # BI & Analytics
    assert ontology.are_synonyms("bi", "business intelligence")
    assert ontology.are_synonyms("power bi", "powerbi")
    assert ontology.are_synonyms("data analytics", "data analysis")
    assert ontology.are_synonyms("eda", "exploratory data analysis")
    assert ontology.are_synonyms("statistics", "statistical analysis")

    # Core ML / DL / APIs
    assert ontology.are_synonyms("ml", "machine learning")
    assert ontology.are_synonyms("dl", "deep learning")
    assert ontology.are_synonyms("rest api", "restful api")
    assert ontology.are_synonyms("api", "rest api")

    # Teaching
    assert ontology.are_synonyms("teaching", "instructor")
    assert ontology.are_synonyms("teacher", "trainer")
    assert ontology.are_synonyms("mentor", "mentoring")

def test_domain_clusters():
    # Vision
    vision_clusters = ontology.get_skill_clusters("opencv")
    assert "Vision" in vision_clusters
    assert "Vision" in ontology.get_skill_clusters("yolo")

    # Cloud
    cloud_clusters = ontology.get_skill_clusters("aws")
    assert "Cloud" in cloud_clusters

    # NLP
    nlp_clusters = ontology.get_skill_clusters("transformers")
    assert "NLP" in nlp_clusters

    # Teaching / STEM
    stem_clusters = ontology.get_skill_clusters("arduino")
    assert "Teaching / STEM" in stem_clusters
    instructor_clusters = ontology.get_skill_clusters("instructor")
    assert "Teaching / STEM" in instructor_clusters

    # Data Analytics
    da_clusters = ontology.get_skill_clusters("power bi")
    assert "Data Analytics" in da_clusters

def test_deduplicate_skills():
    # List containing synonyms that map to same canonical concept
    skills = ["gcp", "google cloud", "python", "google cloud platform", "pytorch", "yolo", "opencv"]
    deduped = ontology.deduplicate_skills(skills)
    
    # "google cloud" and "google cloud platform" are duplicates of "gcp"
    assert "gcp" in deduped
    assert "google cloud" not in deduped
    assert "google cloud platform" not in deduped
    assert "python" in deduped
    assert "pytorch" in deduped
    # Distinct atomic skills are preserved
    assert "yolo" in deduped
    assert "opencv" in deduped

def test_cluster_scoring_and_stuffing_prevention():
    matched_skills = [
        "opencv", "yolo", "cnn", "object detection", "image segmentation",
        "vit", "resnet", "u-net", "aws", "docker"
    ]
    
    # Max points per cluster = 12 (4 skills max at 3 pts each)
    total_score, cluster_breakdown = ontology.calculate_cluster_score(
        matched_skills, base_points_per_skill=3, max_cluster_points=12
    )

    # Even though Vision had 8 skills (which would be 24 pts if uncapped), it should cap at 12
    assert cluster_breakdown.get("Vision", 0) <= 12
    # Cloud has 2 skills -> 6 pts
    assert cluster_breakdown.get("Cloud", 0) == 6
    # Total score should not exceed 12 + 6 = 18 pts
    assert total_score <= 18
