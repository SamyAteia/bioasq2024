#!/usr/bin/env python3
import os
import gzip
import io
from lxml import etree
from opensearchpy import OpenSearch, RequestsHttpConnection
from opensearchpy.helpers import bulk  # Importing bulk from opensearchpy.helpers
from shutil import move  # Importing move from shutil
from dotenv import load_dotenv
import traceback  # Import the traceback module
import concurrent.futures
import time
from datetime import timedelta


# Load environment variables from .env file
load_dotenv()

# Use credentials from .env file
auth = (
    os.getenv('OPENSEARCH_USERNAME', ''),
    os.getenv('OPENSEARCH_PASSWORD', '')
)

# Initialize OpenSearch client with self-signed certificate
es = OpenSearch(
    hosts=[{
        'host': os.getenv('OPENSEARCH_HOST', 'localhost'),
        'port': int(os.getenv('OPENSEARCH_PORT', 9200))
    }],
    http_auth=auth,
    use_ssl=True,
    verify_certs=False,  # Set to True in production with a valid certificate
    ssl_show_warn=False,  # Suppress warning for self-signed certificate
    connection_class=RequestsHttpConnection
)

# Ensure that the index does not exist already
try:
    if not es.indices.exists(index="pubmed_update"):
        resp = es.indices.create(
            index="pubmed_update",
            body={
                "settings": {"number_of_shards": 1, "number_of_replicas": 1},
                "mappings": {
                    "properties": {
                        "title": {"type": "text", "analyzer": "english"},
                        "abstract": {"type": "text", "analyzer": "english"},
                        "url": {"type": "keyword"},
                    }
                },
            },
        )
        print(resp)
except Exception as e:
    print(f"Error creating index: {e}")
    print(traceback.format_exc())  # Print the full stack trace


def parse_xml_content(xml_content):
    """
    Parses XML content from a PubMed database, specifically handling 'PubmedArticleSet'.

    This function processes the XML content, checks for the root element 'PubmedArticleSet', and
    iterates over its children, handling 'PubmedArticle', 'PubmedBookArticle', and 'DeleteCitation' elements.
    For 'PubmedArticle' and 'PubmedBookArticle', it extracts titles, abstracts, and PMIDs.

    Args:
        xml_content (bytes): The XML content to be parsed.

    Returns:
        list of dict: A list of dictionaries, each containing the title, abstract, PMID, and URL of an article or book article.

    Raises:
        etree.XMLSyntaxError: If the XML content is not well-formed.
        ValueError: If the root element is not 'PubmedArticleSet'.
    """

    with io.BytesIO(xml_content) as f:
        tree = etree.parse(f)
        root = tree.getroot()
        if root.tag != 'PubmedArticleSet':
            raise ValueError("Root element is not 'PubmedArticleSet'")

        result = []

        for child in root:
            entry = {"title": None, "abstract": None, "pmid": None, "url": None}

            if child.tag == 'PubmedArticle' or child.tag == 'PubmedBookArticle':
                # Extract PMID
                entry["pmid"] = child.findtext('.//PMID')
                entry["url"] = f"https://pubmed.ncbi.nlm.nih.gov/{entry['pmid']}/"

                if child.tag == 'PubmedArticle':
                    entry["title"] = child.findtext('.//ArticleTitle')
                    abstract_elem = child.find('.//Abstract')
                    if abstract_elem is not None:
                        abstract_texts = abstract_elem.findall('.//AbstractText')
                        entry["abstract"] = ' '.join([text.text for text in abstract_texts if text.text])

                elif child.tag == 'PubmedBookArticle':
                    book_document = child.find('BookDocument')
                    if book_document is not None:
                        entry["title"] = (book_document.findtext('ArticleTitle') or
                                          book_document.findtext('VernacularTitle') or
                                          book_document.find('Book').findtext('BookTitle') if book_document.find('Book') else None)
                        abstract_elem = book_document.find('Abstract')
                        if abstract_elem is not None:
                            abstract_texts = abstract_elem.findall('.//AbstractText')
                            entry["abstract"] = ' '.join([text.text for text in abstract_texts if text.text])

            elif child.tag == 'DeleteCitation':
                continue  # Skip DeleteCitation elements

            if entry["pmid"]:  # Add only if PMID is present
                result.append(entry)
            else:
                raise ValueError("Element has no pmid!")

        root.clear()
        return result



def chunker(seq, size):
    """Yield successive chunks of size from seq."""
    for pos in range(0, len(seq), size):
        yield seq[pos:pos + size]

def process_file(file_path, processed_directory):
    try:
        with gzip.open(file_path, 'rb') as f:
            file_content = f.read()
            articles = parse_xml_content(file_content)

            # Prepare articles for bulk indexing and perform bulk indexing
            actions = [{"_index": "pubmed", "_id": article["pmid"], "_source": article} for article in articles]
            for chunk in chunker(actions, 50):
                bulk(es, list(chunk))

        # Move processed file to the processed directory
        processed_file_path = os.path.join(processed_directory, os.path.basename(file_path))
        move(file_path, processed_file_path)
        print(f"Moved processed file to {processed_file_path}")

    except (OSError, IOError) as e:
        print(f"Error reading file {file_path}: {e}")
        print(traceback.format_exc())  # Print the full stack trace
    except Exception as e:
        print(f"Error indexing file {file_path}: {e}")
        print(traceback.format_exc())  # Print the full stack trace

def index_directory(directory_path, processed_directory):
    """
    Indexes all gzipped XML files in a given directory, moves processed files, and shows progress.

    Args:
        directory_path (str): Path to the directory containing gzipped XML files.
        processed_directory (str): Path to the directory where processed files will be moved.
    """
    start_time = time.time()
    file_paths = [os.path.join(directory_path, file_name) for file_name in os.listdir(directory_path) if file_name.endswith(".xml.gz")]
    total_files = len(file_paths)
    processed_files = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        future_to_file = {executor.submit(process_file, file_path, processed_directory): file_path for file_path in file_paths}

        for future in concurrent.futures.as_completed(future_to_file):
            file_path = future_to_file[future]
            try:
                future.result()
                processed_files += 1
                elapsed_time = time.time() - start_time
                progress = (processed_files / total_files) * 100
                avg_time_per_file = elapsed_time / processed_files
                remaining_time = avg_time_per_file * (total_files - processed_files)
                print(f"Completed indexing {os.path.basename(file_path)}. Progress: {progress:.2f}%. Estimated time left: {timedelta(seconds=remaining_time)}")
            except Exception as e:
                print(f"Error processing file {os.path.basename(file_path)}: {e}")

    total_time = timedelta(seconds=time.time() - start_time)
    print(f"Indexing complete. Total time: {total_time}")


def main():
    # Example usage
    pubmed_dir = "./pubmed_update/"
    processed_dir = "./pubmed_update/processed"

    try:
        index_directory(pubmed_dir, processed_dir)
        print("Indexing complete.")
    except Exception as e:
        print(f"Error during indexing: {e}")
        print(traceback.format_exc())  # Print the full stack trace


if __name__ == "__main__":
    main()