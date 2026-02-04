from src.functions.image_selection.core.prompts import (
    build_image_query,
    build_image_query_prompt,
    EXCLUSION_SUFFIX,
    ACTION_QUERY_PROMPT,
    PORTRAIT_QUERY_PROMPT,
    IMAGE_QUERY_PROMPT_TEMPLATE,
)

def test_build_image_query_adds_context():
    """Test that NFL context is added if missing."""
    query = "Patrick Mahomes"
    result = build_image_query(query)
    
    assert "NFL American football" in result
    assert EXCLUSION_SUFFIX in result

def test_build_image_query_preserves_context():
    """Test that NFL context is not duplicated if present."""
    query = "Patrick Mahomes NFL"
    result = build_image_query(query)
    
    assert result.startswith("Patrick Mahomes NFL")
    assert result.count("NFL") == 1
    assert EXCLUSION_SUFFIX in result

def test_build_image_query_respects_existing_exclusions():
    """Test that custom exclusions prevent default suffix addition."""
    query = "Patrick Mahomes -logo"
    result = build_image_query(query)
    
    assert "NFL American football" in result
    assert EXCLUSION_SUFFIX not in result

def test_build_image_query_prompt_default():
    """Test default template selection."""
    prompt = build_image_query_prompt(
        article_text="Some article text about football",
        max_words=10,
        visual_intent="unknown"
    )
    
    assert "STEP 1 - CLASSIFY the visual type needed" in prompt
    assert "Some article text about football" in prompt

def test_build_image_query_prompt_action():
    """Test action template selection."""
    prompt = build_image_query_prompt(
        article_text="Touchdown run",
        max_words=10,
        visual_intent="action"
    )
    
    assert "focused on GAME ACTION" in prompt
    assert "Touchdown run" in prompt

def test_build_image_query_prompt_portrait():
    """Test portrait template selection."""
    prompt = build_image_query_prompt(
        article_text="Press conference",
        max_words=10,
        visual_intent="portrait"
    )
    
    assert "focused on PORTRAIT/INTERVIEW" in prompt
    assert "Press conference" in prompt

def test_build_image_query_prompt_custom_template():
    """Test custom template usage."""
    custom_template = "Custom template for {article_text}"
    prompt = build_image_query_prompt(
        article_text="Test Article",
        max_words=10,
        template=custom_template
    )
    
    assert prompt == "Custom template for Test Article"
