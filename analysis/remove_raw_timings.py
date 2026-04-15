import json
import os
import glob
import sys
from pathlib import Path


def remove_field_from_json(data, field_to_remove="raw_timings_ms"):
    """Recursively remove a field from JSON data."""
    if isinstance(data, dict):
        # Remove the field if present
        if field_to_remove in data:
            del data[field_to_remove]
        # Recursively process nested dictionaries and lists
        for key, value in data.items():
            data[key] = remove_field_from_json(value, field_to_remove)
        return data
    elif isinstance(data, list):
        # Process each item in the list
        return [remove_field_from_json(item, field_to_remove) for item in data]
    else:
        return data


def process_jsonl_files(input_folder, output_folder=None, field_to_remove="raw_timings_ms", backup_original=False):
    """Process all JSONL files in a folder and remove the specified field."""

    # Find all JSONL files (and optionally JSON files)
    search_pattern = os.path.join(input_folder, "*.jsonl")
    file_paths = glob.glob(search_pattern)

    # Also look for .json files if you have any
    file_paths.extend(glob.glob(os.path.join(input_folder, "*.json")))

    if not file_paths:
        print(f"No JSONL or JSON files found in: {input_folder}")
        return

    print(f"Found {len(file_paths)} files to process")
    print(f"Removing field: '{field_to_remove}'")
    print("-" * 50)

    # If output folder not specified, modify files in place
    if output_folder is None:
        output_folder = input_folder
        print("Mode: Modifying files in place")
    else:
        # Create output folder if it doesn't exist
        os.makedirs(output_folder, exist_ok=True)
        print(f"Mode: Saving cleaned files to: {output_folder}")

    if backup_original and output_folder == input_folder:
        backup_folder = os.path.join(input_folder, "backup_original")
        os.makedirs(backup_folder, exist_ok=True)
        print(f"Backup mode: Originals will be saved to: {backup_folder}")

    print("-" * 50)

    stats = {"processed": 0, "modified": 0, "errors": 0, "total_records_removed": 0}

    for file_path in file_paths:
        filename = os.path.basename(file_path)
        print(f"\nProcessing: {filename}")

        records = []
        records_modified = 0

        try:
            # Read the JSONL file line by line
            with open(file_path, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        record = json.loads(line)
                        # Check if field exists in this record
                        if field_to_remove in record:
                            # Remove the field
                            del record[field_to_remove]
                            records_modified += 1
                        records.append(record)
                    except json.JSONDecodeError as e:
                        print(f"  Warning: Line {line_num} invalid JSON: {e}")
                        # Keep invalid lines as-is? Skip for now.
                        records.append(line)

            if not records:
                print(f"  ⚠ No valid records found")
                stats["processed"] += 1
                continue

            # Determine output path
            if output_folder != input_folder:
                output_path = os.path.join(output_folder, filename)
            else:
                output_path = file_path

                # If modifying in place and backup requested
                if backup_original:
                    backup_path = os.path.join(backup_folder, filename)
                    # Copy original to backup
                    with open(file_path, 'r', encoding='utf-8') as src:
                        with open(backup_path, 'w', encoding='utf-8') as dst:
                            dst.write(src.read())
                    print(f"  📋 Backed up original to: {backup_path}")

            # Write the cleaned data as JSONL
            with open(output_path, 'w', encoding='utf-8') as f:
                for record in records:
                    if isinstance(record, dict):
                        f.write(json.dumps(record) + '\n')
                    else:
                        f.write(str(record) + '\n')

            print(f"  ✓ Removed '{field_to_remove}' from {records_modified} of {len(records)} records")
            stats["modified"] += 1 if records_modified > 0 else 0
            stats["total_records_removed"] += records_modified

        except Exception as e:
            print(f"  ✗ Error: {e}")
            stats["errors"] += 1

        stats["processed"] += 1

    # Print summary
    print("\n" + "=" * 50)
    print("SUMMARY:")
    print(f"  Total files processed: {stats['processed']}")
    print(f"  Files modified: {stats['modified']}")
    print(f"  Total records cleaned: {stats['total_records_removed']}")
    print(f"  Errors: {stats['errors']}")
    print("=" * 50)


if __name__ == "__main__":
    # ============================================
    # EDIT THESE VARIABLES
    # ============================================

    # Folder containing your JSONL result files
    input_folder = r"C:\Users\Ioana\Desktop\UNI\Anul 2\Dizertatie\Dissertation\analysis\baseline_results"

    # OPTIONAL: Save cleaned files to a different folder (set to None to modify in place)
    output_folder = r"C:\Users\Ioana\Desktop\UNI\Anul 2\Dizertatie\Dissertation\analysis\baseline_results\cleaned"
    # output_folder = None  # Uncomment this to modify files in place

    # Field to remove (default is "raw_timings_ms")
    field_to_remove = "raw_timings_ms"

    # Create backups if modifying in place (only works when output_folder = None)
    backup_original = True

    # ============================================
    # RUN THE SCRIPT
    # ============================================
    process_jsonl_files(input_folder, output_folder, field_to_remove, backup_original)