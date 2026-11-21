import re
from typing import Dict, Set, List, Optional, Tuple
from core.text_normalizer import normalize_text, normalize_phrase, lemmatize_word

# Canonical skill groups defining bidirectional synonym relationships
CANONICAL_SKILL_GROUPS: Dict[str, Set[str]] = {
    # Cloud & Infra
    "google cloud": {
        "gcp", "google cloud", "google cloud platform"
    },
    "amazon web services": {
        "aws", "amazon web services"
    },
    "microsoft azure": {
        "azure", "microsoft azure"
    },
    "kubernetes": {
        "kubernetes", "k8s"
    },
    "docker": {
        "docker", "containerization", "containers"
    },
    # AI / Vision
    "computer vision": {
        "cv", "computer vision"
    },
    "opencv": {
        "opencv", "cv2"
    },
    "yolo": {
        "yolo", "yolov5", "yolov8", "yolov11"
    },
    "object detection": {
        "object detection"
    },
    "image segmentation": {
        "image segmentation", "semantic segmentation"
    },
    "image processing": {
        "image processing"
    },
    "convolutional neural network": {
        "cnn", "3d cnn", "convnet", "convolutional neural network"
    },
    "u-net": {
        "u-net", "unet"
    },
    "vit": {
        "vit", "vision transformer"
    },
    # AI / NLP & LLMs
    "natural language processing": {
        "nlp", "natural language processing"
    },
    "llm": {
        "llm", "large language model", "large language models"
    },
    "transformers": {
        "transformers", "transformer"
    },
    "hugging face": {
        "hugging face", "huggingface"
    },
    "generative ai": {
        "genai", "generative ai"
    },
    "rag": {
        "rag", "retrieval augmented generation"
    },
    # AI / Core Learning
    "machine learning": {
        "ml", "machine learning"
    },
    "deep learning": {
        "dl", "deep learning"
    },
    "recurrent neural network": {
        "rnn", "lstm", "gru", "recurrent neural network"
    },
    "scikit-learn": {
        "scikit-learn", "sklearn"
    },
    # Data & Analytics
    "business intelligence": {
        "bi", "business intelligence"
    },
    "power bi": {
        "power bi", "powerbi"
    },
    "tableau": {
        "tableau"
    },
    "dax": {
        "dax"
    },
    "data analysis": {
        "data analysis", "data analytics", "data analyst"
    },
    "exploratory data analysis": {
        "eda", "exploratory data analysis"
    },
    "statistical analysis": {
        "statistics", "statistical analysis", "statistical modeling"
    },
    "relational database": {
        "sql", "relational database", "relational databases", "rdbms", "mysql", "postgresql"
    },
    "data modeling": {
        "data modeling", "star schema", "star-schema", "snowflake schema"
    },
    # Web & APIs
    "rest api": {
        "api", "rest api", "restful api", "web api", "apis"
    },
    "fastapi": {
        "fastapi"
    },
    "flask": {
        "flask"
    },
    "django": {
        "django"
    },
    # Teaching / STEM
    "teaching": {
        "teaching", "teacher", "instructor", "trainer"
    },
    "mentoring": {
        "mentoring", "mentor"
    },
    "curriculum development": {
        "curriculum development", "course design", "curriculum design"
    },
    "stem": {
        "stem"
    },
    "robotics": {
        "robotics"
    },
    "arduino": {
        "arduino"
    },
    "scratch": {
        "scratch"
    },
    "mblock": {
        "mblock"
    },
    "pictoblox": {
        "pictoblox"
    }
}

# Domain Cluster Definitions
DOMAIN_CLUSTERS: Dict[str, Set[str]] = {
    "Cloud": {
        "aws", "amazon web services", "gcp", "google cloud", "google cloud platform",
        "azure", "microsoft azure", "docker", "kubernetes", "k8s", "linux", "cloud computing"
    },
    "Vision": {
        "computer vision", "opencv", "yolo", "object detection", "image segmentation",
        "semantic segmentation", "image processing", "cnn", "3d cnn", "vit", "resnet",
        "u-net", "monai", "torchvision", "albumentations", "mediapipe", "cv"
    },
    "NLP": {
        "nlp", "natural language processing", "llm", "transformers", "hugging face",
        "huggingface", "nltk", "spacy", "bert", "genai", "generative ai", "rag",
        "langchain", "llamaindex", "tf-idf"
    },
    "Deep Learning": {
        "deep learning", "dl", "pytorch", "tensorflow", "keras", "neural networks",
        "cnn", "rnn", "lstm", "vit", "resnet", "u-net"
    },
    "Classical ML": {
        "machine learning", "ml", "scikit-learn", "sklearn", "random forest", "xgboost",
        "classification", "regression", "feature engineering", "predictive modeling",
        "unsupervised learning", "supervised learning", "outlier detection", "hypothesis testing"
    },
    "Data Analytics": {
        "data analysis", "data analytics", "data analyst", "power bi", "tableau", "excel",
        "dax", "business intelligence", "bi", "sql", "mysql", "postgresql", "pandas",
        "numpy", "scipy", "matplotlib", "seaborn", "eda", "exploratory data analysis",
        "data cleaning", "data preprocessing", "etl", "data visualization", "dashboards",
        "kpi", "reporting", "star schema", "data modeling", "statistical analysis", "statistics",
        "a/b testing"
    },
    "DevOps / MLOps": {
        "docker", "kubernetes", "k8s", "git", "github", "ci/cd", "cicd", "mlflow",
        "tensorboard", "model deployment", "airflow", "linux"
    },
    "Teaching / STEM": {
        "instructor", "teacher", "trainer", "teaching", "mentoring", "mentor",
        "curriculum development", "curriculum design", "scratch", "mblock", "pictoblox",
        "stem", "robotics", "arduino"
    }
}


class SkillOntology:
    """
    Skill & Domain Ontology Engine:
    - Provides bidirectional canonical mapping of technical skills and variants.
    - Classifies skills into domain clusters.
    - Performs cluster-aware deduplication to credit core mastery while preventing
      keyword stuffing score inflation.
    """

    def __init__(self):
        self._synonym_to_canonical: Dict[str, str] = {}
        self._canonical_to_synonyms: Dict[str, Set[str]] = {}
        self._canonical_to_patterns: Dict[str, List[re.Pattern]] = {}
        self._canonical_to_lemma_patterns: Dict[str, List[re.Pattern]] = {}
        self._canonical_to_pattern_pairs: Dict[str, List[Tuple[str, re.Pattern]]] = {}
        self._canonical_to_lemma_pattern_pairs: Dict[str, List[Tuple[str, re.Pattern]]] = {}
        self._skill_to_clusters: Dict[str, Set[str]] = {}
        self._build_index()

    def _build_index(self):
        from core.text_normalizer import get_word_pattern

        # 1. Index canonical skill groups
        for canonical, synonyms in CANONICAL_SKILL_GROUPS.items():
            norm_canonical = normalize_phrase(canonical)
            self._canonical_to_synonyms[norm_canonical] = set()

            all_variants = set(synonyms) | {canonical, norm_canonical}
            for syn in all_variants:
                norm_syn = normalize_phrase(syn)
                self._synonym_to_canonical[syn.lower()] = norm_canonical
                self._synonym_to_canonical[norm_syn] = norm_canonical
                self._canonical_to_synonyms[norm_canonical].add(syn.lower())
                self._canonical_to_synonyms[norm_canonical].add(norm_syn)

            sorted_syns = sorted(self._canonical_to_synonyms[norm_canonical], key=lambda s: len(s), reverse=True)
            self._canonical_to_patterns[norm_canonical] = [get_word_pattern(s) for s in sorted_syns]
            self._canonical_to_lemma_patterns[norm_canonical] = [get_word_pattern(normalize_phrase(s)) for s in sorted_syns]
            self._canonical_to_pattern_pairs[norm_canonical] = [(s, get_word_pattern(s)) for s in sorted_syns]
            self._canonical_to_lemma_pattern_pairs[norm_canonical] = [(normalize_phrase(s), get_word_pattern(normalize_phrase(s))) for s in sorted_syns]

        # 2. Index clusters
        for cluster, skills in DOMAIN_CLUSTERS.items():
            for sk in skills:
                sk_clean = sk.lower()
                norm_sk = normalize_phrase(sk_clean)
                canon = self._synonym_to_canonical.get(norm_sk, norm_sk)

                for key in (sk_clean, norm_sk, canon):
                    if key not in self._skill_to_clusters:
                        self._skill_to_clusters[key] = set()
                    self._skill_to_clusters[key].add(cluster)

    def get_synonym_patterns(self, skill: str) -> List[re.Pattern]:
        canon = self.get_canonical_skill(skill)
        if canon in self._canonical_to_patterns:
            return self._canonical_to_patterns[canon]
        from core.text_normalizer import get_word_pattern
        p = get_word_pattern(skill)
        self._canonical_to_patterns[canon] = [p]
        return [p]

    def get_synonym_pattern_pairs(self, skill: str) -> List[Tuple[str, re.Pattern]]:
        canon = self.get_canonical_skill(skill)
        if canon in self._canonical_to_pattern_pairs:
            return self._canonical_to_pattern_pairs[canon]
        from core.text_normalizer import get_word_pattern
        p = get_word_pattern(skill)
        pairs = [(skill.lower(), p)]
        self._canonical_to_pattern_pairs[canon] = pairs
        return pairs

    def get_lemma_pattern_pairs(self, skill: str) -> List[Tuple[str, re.Pattern]]:
        canon = self.get_canonical_skill(skill)
        if canon in self._canonical_to_lemma_pattern_pairs:
            return self._canonical_to_lemma_pattern_pairs[canon]
        from core.text_normalizer import get_word_pattern
        norm_s = normalize_phrase(skill)
        p = get_word_pattern(norm_s)
        pairs = [(norm_s, p)]
        self._canonical_to_lemma_pattern_pairs[canon] = pairs
        return pairs

    def get_lemma_patterns(self, skill: str) -> List[re.Pattern]:
        canon = self.get_canonical_skill(skill)
        if canon in self._canonical_to_lemma_patterns:
            return self._canonical_to_lemma_patterns[canon]
        from core.text_normalizer import get_word_pattern
        p = get_word_pattern(normalize_phrase(skill))
        self._canonical_to_lemma_patterns[canon] = [p]
        return [p]

    def get_canonical_skill(self, skill: str) -> str:
        """Resolves any synonym or variant to its canonical representation."""
        if not skill:
            return ""
        s_clean = skill.strip().lower()
        if s_clean in self._synonym_to_canonical:
            return self._synonym_to_canonical[s_clean]
        s_norm = normalize_phrase(s_clean)
        return self._synonym_to_canonical.get(s_norm, s_norm)

    def get_synonyms(self, skill: str) -> Set[str]:
        """Returns all recognized synonyms and variants for a skill."""
        canon = self.get_canonical_skill(skill)
        return self._canonical_to_synonyms.get(canon, {skill.strip().lower()})

    def are_synonyms(self, skill_a: str, skill_b: str) -> bool:
        """Checks if two skill strings represent the same canonical concept."""
        if not skill_a or not skill_b:
            return False
        canon_a = self.get_canonical_skill(skill_a)
        canon_b = self.get_canonical_skill(skill_b)
        return canon_a == canon_b

    def get_skill_clusters(self, skill: str) -> Set[str]:
        """Returns the domain clusters (Cloud, Vision, NLP, etc.) for a skill."""
        if not skill:
            return set()
        s_clean = skill.strip().lower()
        if s_clean in self._skill_to_clusters:
            return self._skill_to_clusters[s_clean]
        canon = self.get_canonical_skill(skill)
        return self._skill_to_clusters.get(canon, set())

    def deduplicate_skills(self, skills: List[str]) -> List[str]:
        """
        Deduplicates a list of skills by canonical representation while preserving
        original order.
        """
        seen = set()
        deduped = []
        for sk in skills:
            if not sk or not str(sk).strip():
                continue
            canon = self.get_canonical_skill(sk)
            if canon not in seen:
                seen.add(canon)
                deduped.append(sk)
        return deduped

    def cluster_skills(self, skills: List[str]) -> Dict[str, List[str]]:
        """Groups a list of skills into domain clusters."""
        res: Dict[str, List[str]] = {cluster: [] for cluster in DOMAIN_CLUSTERS}
        res["Other"] = []

        deduped = self.deduplicate_skills(skills)
        for sk in deduped:
            clusters = self.get_skill_clusters(sk)
            if clusters:
                for c in clusters:
                    res[c].append(sk)
            else:
                res["Other"].append(sk)
        return res

    def calculate_cluster_score(
        self,
        matched_skills: List[str],
        base_points_per_skill: int = 3,
        max_cluster_points: int = 12
    ) -> Tuple[int, Dict[str, int]]:
        """
        Cluster-aware scoring to credit breadth across domains and core mastery,
        while strictly preventing keyword stuffing in a single domain.
        
        Args:
            matched_skills: List of skills matched in job description.
            base_points_per_skill: Points awarded per skill match (default: 3).
            max_cluster_points: Maximum score contribution allowed from any single cluster (default: 12).
            
        Returns:
            (total_score, cluster_breakdown_dict)
        """
        deduped = self.deduplicate_skills(matched_skills)
        cluster_map = self.cluster_skills(deduped)
        cluster_scores = {}
        total = 0

        scored_skills = set()

        for cluster, skills in cluster_map.items():
            if not skills:
                continue
            raw_pts = 0
            for sk in skills:
                canon = self.get_canonical_skill(sk)
                if canon not in scored_skills:
                    raw_pts += base_points_per_skill
                    scored_skills.add(canon)
            if cluster == "Other":
                capped_pts = raw_pts
            else:
                capped_pts = min(raw_pts, max_cluster_points) if max_cluster_points is not None else raw_pts
            cluster_scores[cluster] = capped_pts
            total += capped_pts

        return total, cluster_scores


# Global singleton instance
ontology = SkillOntology()
