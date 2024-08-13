- Run in virtual env bioasq `source bioasq/bin/activate`  
- `pip install opensearch-py python-dotenv lxml shutil`  


You have to download the 2024 snapshot of the [pubmed anual baseline](https://lhncbc.nlm.nih.gov/ii/information/MBR.html) into a folder and adapt the example indexing script to work with your folder structure and version of opensearch or elasticsearch.

You have to create a .env file in the folder where you are executing index_pubmed.py with the following variables:
OPENSEARCH_USERNAME  
OPENSEARCH_PASSWORD  
OPENSEARCH_HOST  
OPENSEARCH_PORT  

First index the anual baseline into the index `pubmed` (see process_file function) then if you want to also recreate the results for synergy change the index name to `pubmed_update` and index the update files up to the specific date published on the biosasq website that correspond to the synergy batch you want to recreate.