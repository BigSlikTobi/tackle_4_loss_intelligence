# Cloud Function Deployment (Future)

This directory will contain Cloud Function deployment code for scheduled knowledge extraction.

## Planned Features

- **Scheduled Extraction**: Automatically extract knowledge from new story groups
- **HTTP API**: Trigger extraction via HTTP endpoint
- **Progress Tracking**: Monitor extraction progress
- **Error Handling**: Retry failed extractions

## Current Status

⏳ Not yet implemented - use CLI script for now:

```bash
cd src/functions/knowledge_extraction
python scripts/extract_knowledge_cli.py
```

## Future Implementation

The Cloud Function will expose an HTTP endpoint similar to other modules:

```python
# main.py (future)
from flask import Flask, request, jsonify
from src.functions.knowledge_extraction.core.pipelines.extraction_pipeline import (
    ExtractionPipeline
)

app = Flask(__name__)

@app.route('/extract-knowledge', methods=['POST'])
def extract_knowledge():
    """Extract knowledge from story groups."""
    data = request.get_json()
    limit = data.get('limit')
    
    pipeline = ExtractionPipeline()
    results = pipeline.run(limit=limit)
    
    return jsonify(results)
```

See `data_loading/functions/` and `content_summarization/functions/` for deployment examples.
