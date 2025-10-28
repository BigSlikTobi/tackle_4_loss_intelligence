"""
Integration tests for the Daily Team Update Pipeline components.

Tests individual service integrations and end-to-end workflows.
"""

import pytest
from typing import Dict, Any

from tests.integration.fixtures import (
    get_sample_team,
    get_sample_urls,
    get_sample_extracted_content,
    get_sample_summaries,
    get_sample_article,
    get_sample_translation,
)


class TestContentExtractionToSummarization:
    """Test content extraction → summarization flow."""
    
    def test_extracted_content_structure(self):
        """Verify extracted content has required fields for summarization."""
        content = get_sample_extracted_content()[0]
        
        # Required fields for summarization
        assert "content" in content
        assert "url" in content
        assert "title" in content
        
        # Content should not be empty
        assert len(content["content"]) > 0
        assert len(content["paragraphs"]) > 0
    
    def test_summary_from_extracted_content(self):
        """Test that extracted content can be summarized."""
        from src.functions.article_summarization.core.contracts.summary import SummarizationRequest
        
        content = get_sample_extracted_content()[0]
        
        # Create summarization request
        request = SummarizationRequest(
            article_id="test-article-1",
            content=content["content"],
            team_name="Kansas City Chiefs",
            url=content["url"]
        )
        
        # Verify request is valid
        assert request.article_id == "test-article-1"
        assert len(request.content) > 0
        assert request.team_name == "Kansas City Chiefs"


class TestSummarizationToArticleGeneration:
    """Test summarization → article generation flow."""
    
    def test_summary_bundle_creation(self):
        """Verify summaries can be bundled for article generation."""
        from src.functions.team_article_generation.core.contracts.team_article import SummaryBundle
        
        summaries = get_sample_summaries()
        team = get_sample_team("KC")
        
        # Create bundle
        bundle = SummaryBundle(
            team_name=team["name"],
            team_abbr=team["abbreviation"],
            summaries=[s["content"] for s in summaries]
        )
        
        # Verify bundle is valid
        assert bundle.team_name == "Kansas City Chiefs"
        assert bundle.team_abbr == "KC"
        assert len(bundle.summaries) == 2
        assert len(bundle.summaries[0]) > 0
    
    def test_article_structure(self):
        """Verify generated article has required fields."""
        article = get_sample_article()
        
        # Required fields
        assert "headline" in article
        assert "sub_header" in article
        assert "introduction_paragraph" in article
        assert "content" in article
        
        # Content structure
        assert len(article["headline"]) > 0
        assert len(article["sub_header"]) > 0
        assert len(article["introduction_paragraph"]) > 0
        assert len(article["content"]) >= 2  # At least 2 paragraphs


class TestArticleGenerationToTranslation:
    """Test article generation → translation flow."""
    
    def test_translation_request_creation(self):
        """Verify article can be translated."""
        from src.functions.article_translation.core.contracts.translated_article import TranslationRequest
        
        article = get_sample_article()
        
        # Create translation request
        request = TranslationRequest(
            article_id="test-article-1",
            language="de",
            headline=article["headline"],
            sub_header=article["sub_header"],
            introduction_paragraph=article["introduction_paragraph"],
            content=article["content"]
        )
        
        # Verify request is valid
        assert request.article_id == "test-article-1"
        assert request.language == "de"
        assert len(request.headline) > 0
        assert len(request.content) > 0
    
    def test_translation_preserves_structure(self):
        """Verify translation preserves article structure."""
        article = get_sample_article()
        translation = get_sample_translation()
        
        # Structure should match
        assert len(translation["content"]) == len(article["content"])
        assert translation["headline"] != article["headline"]  # Should be different language
        assert len(translation["headline"]) > 0


class TestFullPipelineFlow:
    """Test full pipeline with test data."""
    
    def test_pipeline_data_flow(self):
        """Test data flows correctly through all stages."""
        team = get_sample_team("KC")
        urls = get_sample_urls("KC")
        contents = get_sample_extracted_content()
        summaries = get_sample_summaries()
        article = get_sample_article()
        translation = get_sample_translation()
        
        # Verify team data
        assert team["abbreviation"] == "KC"
        assert team["name"] == "Kansas City Chiefs"
        
        # Verify URLs
        assert len(urls) > 0
        assert all(url.startswith("https://") for url in urls)
        
        # Verify content extraction
        assert len(contents) > 0
        for content in contents:
            assert "content" in content
            assert len(content["content"]) > 0
        
        # Verify summarization
        assert len(summaries) > 0
        for summary in summaries:
            assert "content" in summary
            assert summary["word_count"] > 0
        
        # Verify article generation
        assert article["headline"]
        assert len(article["content"]) >= 2
        
        # Verify translation
        assert translation["language"] == "de"
        assert len(translation["content"]) == len(article["content"])
    
    def test_error_handling_in_pipeline(self):
        """Test that pipeline handles errors gracefully."""
        # Test with invalid data
        from src.functions.article_summarization.core.contracts.summary import SummarizationRequest
        
        # Empty content should raise validation error
        with pytest.raises(Exception):  # ValidationError from pydantic
            request = SummarizationRequest(
                article_id="test",
                content="",
                team_name="Chiefs"
            )
        
        # Valid content with 25+ words should work
        request = SummarizationRequest(
            article_id="test",
            content="""This is a test article about the Chiefs with enough content words 
            to pass validation checks and requirements for meaningful summarization processing 
            with proper length and substance for testing purposes.""",
            team_name="Chiefs"
        )
        
        assert request.article_id == "test"
        assert len(request.content) > 0


class TestDataQuality:
    """Test data quality assertions."""
    
    def test_summary_quality(self):
        """Test summaries meet quality standards."""
        summaries = get_sample_summaries()
        
        for summary in summaries:
            # Word count should be reasonable
            assert 40 <= summary["word_count"] <= 200
            
            # Should have processing metrics
            assert summary["processing_time_ms"] > 0
            assert summary["tokens_used"] > 0
            
            # Content should not be empty
            assert len(summary["content"]) > 0
    
    def test_article_quality(self):
        """Test article meets quality standards."""
        article = get_sample_article()
        
        # Headline should be compelling
        assert len(article["headline"]) > 10
        assert len(article["headline"]) < 100
        
        # Introduction should set context
        assert len(article["introduction_paragraph"]) > 50
        
        # Content should have multiple paragraphs
        assert len(article["content"]) >= 2
        
        # Each paragraph should have substance
        for paragraph in article["content"]:
            assert len(paragraph) > 50
    
    def test_translation_quality(self):
        """Test translation meets quality standards."""
        translation = get_sample_translation()
        
        # Should preserve key terms
        assert len(translation["preserved_terms"]) > 0
        
        # Should have all required fields
        assert translation["headline"]
        assert translation["sub_header"]
        assert translation["introduction_paragraph"]
        assert len(translation["content"]) > 0


class TestContractCompatibility:
    """Test that data contracts are compatible across modules."""
    
    def test_extracted_content_to_summarization_contract(self):
        """Test extracted content matches summarization input contract."""
        from src.functions.article_summarization.core.contracts.summary import SummarizationRequest
        
        content = get_sample_extracted_content()[0]
        
        # Should be able to create request without errors
        request = SummarizationRequest(
            article_id="test",
            content=content["content"],
            team_name="Chiefs",
            url=content["url"]
        )
        
        assert request is not None
    
    def test_summary_to_article_generation_contract(self):
        """Test summaries match article generation input contract."""
        from src.functions.team_article_generation.core.contracts.team_article import SummaryBundle
        
        summaries = get_sample_summaries()
        
        # Should be able to create bundle without errors
        bundle = SummaryBundle(
            team_name="Kansas City Chiefs",
            team_abbr="KC",
            summaries=[s["content"] for s in summaries]
        )
        
        assert bundle is not None
    
    def test_article_to_translation_contract(self):
        """Test article matches translation input contract."""
        from src.functions.article_translation.core.contracts.translated_article import TranslationRequest
        
        article = get_sample_article()
        
        # Should be able to create request without errors
        request = TranslationRequest(
            article_id="test",
            language="de",
            headline=article["headline"],
            sub_header=article["sub_header"],
            introduction_paragraph=article["introduction_paragraph"],
            content=article["content"]
        )
        
        assert request is not None
