"""Quick script to reprocess a batch output file."""
import sys
from pathlib import Path

# Bootstrap
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from src.shared.utils.env import load_env
from src.functions.knowledge_extraction.core.batch.result_processor import BatchResultProcessor

# Load environment variables
load_env()

# Get batch output file from command-line argument or use default
if len(sys.argv) > 1:
    output_file = Path(sys.argv[1])
else:
    output_file = Path(__file__).parent.parent / 'batch_690b4856dacc8190ad2d2d90e7c300d7_output.jsonl'

if not output_file.exists():
    print(f'File not found: {output_file.absolute()}')
    sys.exit(1)

print(f'Processing: {output_file.name}')
print()

# Process with write to DB
processor = BatchResultProcessor()
result = processor.process(output_file, dry_run=False)

print(f'\n{"="*80}')
print(f'RESULTS')
print(f'{"="*80}')
print(f'Groups processed: {result.groups_processed}')
print(f'Topics extracted: {result.topics_extracted}')
print(f'Entities extracted: {result.entities_extracted}')
print(f'Groups with errors: {result.groups_with_errors}')
if result.errors:
    print(f'\nFirst 5 errors:')
    for error in result.errors[:5]:
        print(f'  - {error}')
