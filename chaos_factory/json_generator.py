import json
import random
import argparse
import urllib.request
import os
import pickle
import logging
from multiprocessing import Pool, cpu_count

# Brief Description:
# This script generates a JSON file containing a set of records. Each record includes a random phrase
# and simulated execution times for a hypothetical query process. The script utilizes multiprocessing
# to efficiently generate records and manages word lists through a custom class that can load words
# from a URL or a local pickle file.

class WordList:
    """Class to manage a list of words."""
    def __init__(self, word_list_url, pickle_file_path):
        """Initialize the WordList with a URL and a file path."""
        self.words = None
        self.load_words(word_list_url, pickle_file_path)

    def load_words(self, word_list_url, pickle_file_path):
        """Load words from a URL or a pickle file."""
        try:
            # If pickle file doesn't exist, download the word list and save it
            if not os.path.exists(pickle_file_path):
                response = urllib.request.urlopen(word_list_url)
                long_txt = response.read().decode()
                self.words = long_txt.splitlines()
                with open(pickle_file_path, 'wb') as file:
                    pickle.dump(self.words, file)
                logging.info(f"Downloaded the word list and saved to '{pickle_file_path}'.")
            else:
                # If pickle file exists, load the word list from it
                with open(pickle_file_path, 'rb') as file:
                    self.words = pickle.load(file)
                logging.info(f"Loaded word list from '{pickle_file_path}'.")
        except Exception as e:
            logging.error(f"An error occurred: {e}")

    def get_random_words(self, word_count: int) -> str:
        """Get a random phrase consisting of 'word_count' words."""
        # Filter out proper nouns and acronyms
        upper_words = [word for word in self.words if not word[0].isupper()]
        name_words = [word for word in upper_words if not word.isupper()]
        # Generate a random phrase
        rand_name = ' '.join(random.choice(name_words) for _ in range(word_count))
        return rand_name

def generate_record(args):
    """Generate a single record with random data."""
    count, word_list_instance = args

    # Define base values for query and process times
    base_query_time = 15
    base_process_time = 5

    # Add random jitter to simulate variability in execution times
    query_time = base_query_time + random.uniform(-2, 4)  # Jitter within [-2, 4]
    process_time = base_process_time + random.uniform(-1.5, 5)  # Jitter within [-1.5, 5]

    # Calculate total execution time
    total_exec_time = query_time + process_time

    # Generate a random comment using the WordList instance
    comments = word_list_instance.get_random_words(random.randint(5,40))

    # Return a dictionary representing the record
    return {
        "count": count,
        "queryTime": query_time,
        "totalExecTime": total_exec_time,
        "processTime": process_time,
        "comments": comments
    }

def generate_json_table(num_records, output_name, word_list_instance):
    # Define the number of records per file
    records_per_file = 5000  # Adjust this number based on your needs

    # Create a pool of workers equal to the number of CPU cores
    with Pool(cpu_count()) as p:
        for i in range(0, num_records, records_per_file):
            # Calculate the range for the current batch
            start = i
            end = min(i + records_per_file, num_records)
            
            # Generate records for the current batch
            record_batch = p.map(generate_record, [(count, word_list_instance) for count in range(start, end)])
            output_dir = os.path.dirname(output_name)
            # Define the output file name for the current batch
            batch_output_name = os.path.join(output_dir, f"tmp_records_{start}_{end}.json")
            
            # Save the current batch of records to a JSON file without the JSON object wrapper
            with open(batch_output_name, "w") as f:
                # Dump the list directly instead of a dict with the "recordset" key
                json.dump(record_batch, f, indent=4)
            print(f"Saved {batch_output_name}")

    # Once all batches are saved, append them together with the correct JSON format
    with open(output_name, "w") as outfile:
        outfile.write('{"recordset": [\n')  # Start of the JSON object
        for i in range(0, num_records, records_per_file):
            start = i
            end = min(i + records_per_file, num_records)
            batch_output_name = os.path.join(output_dir, f"tmp_records_{start}_{end}.json")
            with open(batch_output_name, "r") as infile:
                # Append the contents of each file, stripping the brackets
                outfile.write(infile.read().strip("[]"))
                if end < num_records:
                    outfile.write(",\n")  # Add a comma between batches, except after the last batch
        outfile.write('\n]}')  # End of the JSON object

    # Delete the temporary files
    for i in range(0, num_records, records_per_file):
        start = i
        end = min(i + records_per_file, num_records)
        batch_output_name = os.path.join(output_dir, f"tmp_records_{start}_{end}.json")
        os.remove(batch_output_name)
        print(f"Deleted {batch_output_name}")
        
def main():
    """Main function to parse arguments and generate JSON table."""
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description='Generate a JSON table.')
    parser.add_argument('rows', type=int, help='Number of rows to generate')
    parser.add_argument('output', type=str, help='Output file name')
    parser.add_argument('--word_list_url', type=str, default="https://www.mit.edu/~ecprice/wordlist.10000", help='URL to fetch the word list from')
    parser.add_argument('--pickle_file_path', type=str, default='wordlist.pkl', help='Path to save/load the word list pickle file')
    
    args = parser.parse_args()
    if args.rows <= 0:
        parser.error("Number of rows must be a positive integer greater than 0")

    # Create an instance of the WordList class with the optional arguments
    word_list_instance = WordList(args.word_list_url, args.pickle_file_path)
    
    generate_json_table(num_records=args.rows, output_name=args.output, word_list_instance=word_list_instance)

if __name__ == "__main__":
    main()
