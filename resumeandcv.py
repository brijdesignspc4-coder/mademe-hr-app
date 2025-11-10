import os
import re
import json
from langchain_community.document_loaders import PyPDFLoader, UnstructuredWordDocumentLoader
from langchain_ollama import OllamaLLM
import json
import re
from collections import OrderedDict
from app import flatten_for_db

EXTRACTOR_MODEL = os.environ.get("EXTRACTOR_MODEL", "llama3.2:1b")
FIELDS = [
    "name", "contact", "email", "position", "languages", "qualification", "experience",
    "current_company", "current_salary", "expected_salary", "in_hand_salary",
    "permanent_address", "current_address", "skills", "switching_reason"
]

def extract_resume_text(file_path):
    import os
    from langchain_community.document_loaders import PyPDFLoader, UnstructuredWordDocumentLoader

    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        loader = PyPDFLoader(file_path)
        docs = loader.load()
        return " ".join([d.page_content for d in docs])

    elif ext in [".doc", ".docx"]:
        # Try with UnstructuredWordDocumentLoader first
        try:
            loader = UnstructuredWordDocumentLoader(file_path)
            docs = loader.load()
            return " ".join([d.page_content for d in docs])
        except Exception as e:
            print(f" Unstructured loader failed for Word file, trying fallback: {e}")

            # Fallback to docx2txt (works with 99% of docx resumes)
            try:
                import docx2txt
                text = docx2txt.process(file_path)
                return text or ""
            except Exception as e2:
                raise ValueError(f" Failed to read Word file: {e2}")

    else:
        raise ValueError("Unsupported file format. Please upload PDF or Word files only.")

def parse_llm_json_safe(raw_output: str):
    """Attempt to clean and parse slightly malformed LLM JSON safely."""
    if not raw_output:
        return {}

    # Remove any unwanted text before/after JSON
    raw_output = raw_output.strip()
    raw_output = re.sub(r'^[^{]*', '', raw_output)  # remove text before first {
    raw_output = re.sub(r'[^}]*$', '', raw_output)  # remove text after last }

    # Try to balance braces/brackets if model forgets closing ones
    open_braces = raw_output.count("{")
    close_braces = raw_output.count("}")
    if close_braces < open_braces:
        raw_output += "}" * (open_braces - close_braces)

    # Remove trailing commas before } or ]
    raw_output = re.sub(r',(\s*[}\]])', r'\1', raw_output)

    try:
        return json.loads(raw_output)
    except json.JSONDecodeError as e:
        print(f" JSON parsing failed even after cleanup: {e}")
        print("Cleaned output:", raw_output)
        return {}



def safe_json_parse(raw_text: str):
    """
    Extracts and cleans JSON from raw LLM output.
    Handles duplicate keys, missing commas, unquoted 'Not available', and trailing text.
    """

    # 1️ Extract just the JSON portion
    match = re.search(r'\{.*\}', raw_text, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in text")
    json_str = match.group(0)

    # 2️ Fix common issues
    json_str = re.sub(r':\s*Not available', ': "Not available"', json_str)
    json_str = re.sub(r':\s*None\b', ': "Not available"', json_str)
    json_str = re.sub(r':\s*null\b', ': "Not available"', json_str)
    json_str = re.sub(r"'", '"', json_str)  # unify quotes
    json_str = re.sub(r',\s*}', '}', json_str)  # remove trailing commas

    # 3️ Try normal parse first
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass  # continue to fallback

    # 4️ Fallback: parse line by line, keep only last duplicate key
    pairs = re.findall(r'"([^"]+)":\s*(.*?)(?=,\s*"|}$)', json_str, re.DOTALL)
    data = OrderedDict()
    for key, val in pairs:
        # Normalize value
        val = val.strip().rstrip(',')
        if val in ('null', 'None', 'Not available', '"Not available"'):
            val = "Not available"
        elif val.startswith('[') or val.startswith('{'):
            try:
                val = json.loads(val)
            except Exception:
                val = "Not available"
        else:
            val = val.strip('"')
        data[key] = val

    return dict(data)

def parse_resume_with_llm(resume_text: str):
    llm = OllamaLLM(model=EXTRACTOR_MODEL)
    prompt = f"""
Extract the following fields in valid JSON only.
Output ONE JSON object.

Fields:
{', '.join(FIELDS)}

If a field is missing, return "" for strings and [] for lists.

Resume Text:
{resume_text}
"""
    try:
        raw_output = llm.invoke(prompt)
        data = parse_llm_json_safe(raw_output)
    except Exception as e:
        print(f" LLM or JSON parsing failed: {e}")
        data = {}

    for f in FIELDS:
        if f not in data or not data[f]:
            data[f] = [] if f in ["skills", "languages", "experience"] else "Not available"

    return data

def process_resume(file_path):
    resume_text = extract_resume_text(file_path)
    candidate_data = parse_resume_with_llm(resume_text)
    candidate_data["file_name"] = os.path.basename(file_path)
    candidate_data["status"] = "Pending"

    for k, v in candidate_data.items():
        candidate_data[k] = flatten_for_db(v)
    print(f" Resume processed successfully for '{candidate_data.get('name', 'Unknown')}'")
