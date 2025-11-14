import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))

from src.functions.url_content_extraction.functions.main import handle_request

result = handle_request({
    'urls': ['https://sny.tv/articles/giants-reuniting-wide-receiver-isaiah-hodgins']
})

article = result['articles'][0]
print('=== SNY.tv Final Test ===')
print(f"Status: {result['status']}")
print(f"Has error: {'error' in article}")

if 'error' not in article:
    print(f"Word count: {article.get('word_count', 0)}")
    print(f"Paragraph count: {len(article.get('paragraphs', []))}")
    print(f"Title: {article.get('title', '')}")
    
    content = article.get('content', '')
    print('\n✓ Successfully extracted clean content!')
    print('\nFirst 500 chars:')
    print(content[:500])
    
    paragraphs = article.get('paragraphs', [])
    if len(paragraphs) >= 3:
        print('\nSample paragraphs:')
        for i in [0, 1, min(5, len(paragraphs)-1)]:
            print(f"  [{i+1}]: {paragraphs[i][:100]}...")
