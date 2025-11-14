import sys
import json

data = json.load(sys.stdin)
article = data['articles'][0]

print(f"Status: {data['status']}")
print(f"Has error: {'error' in article}")

if 'error' in article:
    print(f"Error: {article['error'][:200]}")
else:
    print(f"Word count: {article.get('word_count', 0)}")
    print(f"Paragraph count: {len(article.get('paragraphs', []))}")
    print(f"Title: {article.get('title', '')}")
    print(f"\nFirst 400 chars:")
    print(article.get('content', '')[:400])
