import json
import os
import glob
from pathlib import Path


def merge_json_files_from_folder(folder_path, output_path, file_pattern="*.json"):
    """Merge all JSON/JSONL files from a folder into a single JSONL output."""
    merged_records = []

    # Find all JSON files in the folder
    search_pattern = os.path.join(folder_path, file_pattern)
    file_paths = glob.glob(search_pattern)

    if not file_paths:
        print(f"No files found matching: {search_pattern}")
        return

    print(f"Found {len(file_paths)} files to merge:")
    for f in file_paths:
        print(f"  - {os.path.basename(f)}")
    print()

    for file_path in file_paths:
        print(f"Reading: {os.path.basename(file_path)}")
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()

            if not content:
                print(f"  Skipping empty file")
                continue

            # Try parsing as JSON array first
            try:
                data = json.loads(content)
                if isinstance(data, list):
                    merged_records.extend(data)
                    print(f"  Added {len(data)} records (JSON array)")
                    continue
                elif isinstance(data, dict):
                    merged_records.append(data)
                    print(f"  Added 1 record (JSON object)")
                    continue
            except json.JSONDecodeError:
                pass

            # Try parsing as JSONL (one object per line)
            lines = content.split('\n')
            line_count = 0
            for line_num, line in enumerate(lines, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    merged_records.append(record)
                    line_count += 1
                except json.JSONDecodeError as e:
                    print(f"  Warning: Line {line_num} invalid JSON: {e}")

            if line_count > 0:
                print(f"  Added {line_count} records (JSONL)")

    # Create output directory if it doesn't exist
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"\nCreated directory: {output_dir}")

    # Write merged output as JSONL
    print(f"\nWriting {len(merged_records)} total records to: {output_path}")
    with open(output_path, 'w', encoding='utf-8') as f:
        for record in merged_records:
            f.write(json.dumps(record) + '\n')

    print("Done!")


if __name__ == "__main__":
    # ============================================
    # EDIT THESE TWO VARIABLES
    # ============================================

    # Folder containing your JSON result files
    input_folder = r"C:\Users\Ioana\Desktop\UNI\Anul 2\Dizertatie\Dissertation\benchmarks\cassandra\results\write"

    # Where to save the merged result (full path + filename)
    output_file = r"/analysis/write_results/merged_cassandra_write.jsonl"

    # Optional: Change file pattern if needed (e.g., "*_baseline.json", "q*.json")
    file_pattern = "*.json"  # Merges all .json files

    # ============================================
    # RUN THE MERGE
    # ============================================
    merge_json_files_from_folder(input_folder, output_file, file_pattern)