import types
from sklearn.neighbors import NearestNeighbors
import tensorflow_hub as hub
import numpy as np
import fitz
from pathlib import Path
import urllib.request
import re
import json
import os
from openai import OpenAI

client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
import os
import docx
import base64
from dotenv import load_dotenv
load_dotenv()
os.environ['OPENAI_API_KEY'] = os.getenv('OPENAI_API_KEY')

recommender_list = {}

# Function to encode the image


def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')


def call_gpt3(messages, n=1, temperature=1, model='gpt-3.5-turbo-16k', image_path: str = "") -> str:
    if image_path != None and image_path != "":
        response = client.chat.completions.create(model="gpt-4-vision-preview",
        messages=messages +
        [{"content": [
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{encode_image(str(image_path))}"
                }
            }
        ], "role": "user"}],
        temperature=temperature, n=n)
        print(response)

    else:
        response = client.chat.completions.create(model=model,
        messages=messages,
        temperature=temperature, n=n)
        cost_prompt = float(response["usage"]["prompt_tokens"])/1000*0.001
        cost_completion_tokens = float(
            response["usage"]["completion_tokens"])/1000*0.002
        print(cost_prompt + cost_completion_tokens)
    return response


def preprocess(text):
    text = text.replace('\n', ' ')
    text = re.sub('\s+', ' ', text)
    return text


def text_to_chunks(texts, word_length=150, start_page=1):
    text_toks = [t.split(' ') for t in texts]
    chunks = []

    for idx, words in enumerate(text_toks):
        for i in range(0, len(words), word_length):
            chunk = words[i: i + word_length]
            if (
                (i + word_length) > len(words)
                and (len(chunk) < word_length)
                and (len(text_toks) != (idx + 1))
            ):
                text_toks[idx + 1] = chunk + text_toks[idx + 1]
                continue
            chunk = ' '.join(chunk).strip()
            chunk = f'[Page no. {idx+start_page}]' + ' ' + '"' + chunk + '"'
            chunks.append(chunk)
    return chunks


def read_txt(file_path):
    with open(file_path, 'r') as file:
        text = file.read()
    return [preprocess(text)]


def read_docx(file_path):
    text = []
    doc = docx.Document(file_path)
    for paragraph in doc.paragraphs:
        text.append(paragraph.text)
    return [preprocess('\n'.join(text))]


def pdf_to_text(file_path, start_page=1, end_page=None):
    doc = fitz.open(file_path)
    total_pages = doc.page_count

    if end_page is None:
        end_page = total_pages

    text_list = []

    for i in range(start_page - 1, end_page):
        text = doc.load_page(i).get_text("text")
        text = preprocess(text)
        text_list.append(text)

    doc.close()
    return text_list


def file_to_text(file_path, start_page=1):
    _, file_extension = os.path.splitext(file_path)
    if file_extension == ".pdf":
        return pdf_to_text(file_path, start_page=start_page)
    elif file_extension == ".txt":
        return read_txt(file_path)
    elif file_extension == ".docx":
        return read_docx(file_path)
    else:
        raise ValueError("File format not supported")


def load_recommender(path, start_page=1, end_page=None):
    global recommender_list
    recommender = SemanticSearch()
    recommender_list[path] = recommender
    texts = file_to_text(path, start_page=start_page)
    chunks = text_to_chunks(texts, start_page=start_page)
    recommender.fit(chunks)
    return 'Corpus Loaded.'


class SemanticSearch:
    def __init__(self):
        self.use = hub.load('universal-sentence-encoder_4')
        self.fitted = False

    def fit(self, data, batch=1000, n_neighbors=5):
        self.data = data
        self.embeddings = self.get_text_embedding(data, batch=batch)
        n_neighbors = min(n_neighbors, len(self.embeddings))
        self.nn = NearestNeighbors(n_neighbors=n_neighbors)
        self.nn.fit(self.embeddings)
        self.fitted = True

    def __call__(self, text, return_data=True):
        inp_emb = self.use([text])
        neighbors = self.nn.kneighbors(inp_emb, return_distance=False)[0]

        if return_data:
            return [self.data[i] for i in neighbors]
        else:
            return neighbors

    def get_text_embedding(self, texts, batch=1000):
        embeddings = []
        for i in range(0, len(texts), batch):
            text_batch = texts[i: (i + batch)]
            emb_batch = self.use(text_batch)
            embeddings.append(emb_batch)
        embeddings = np.vstack(embeddings)
        return embeddings


def generate_text(prompt, image=None, engine='gpt-3.5-turbo-16k'):
    try:
        messages = [{"content": prompt, "role": "user"}]
        completions = call_gpt3(messages, image_path=image, n=1, model=engine)
        message = completions['choices'][0]['message']['content']
    except Exception as e:
        message = f'API Error: {str(e)}'
    return message


def generate_flashcards(file_paths=[], context=""):

    # get the first 2 pages of each file
    prompt = '''You are flashcardGPT, an AI designed to look at random extracts from a stundent's course material and generate flashcards for them. \n\n Your output should be a fully planned out flashcard unit for the given material. \n\n 
     Your student's context :''' + context + '''\n\nYour student's material: \n\nYour output should be json of the following format: \n\n
     ***
{
       "flashcards": [
    {
      "question": "What is Cognitive Dissonance?",
      "answer": "Cognitive Dissonance is a psychological concept referring to the discomfort felt when holding two or more conflicting beliefs, values, or attitudes."
    },
    {
      "question": "Who proposed the Cognitive Dissonance Theory and when?",
      "answer": "Leon Festinger proposed the Cognitive Dissonance Theory in 1957."
    },
    {
      "question": "How do people reduce the tension caused by cognitive dissonance?",
      "answer": "People reduce the tension caused by cognitive dissonance by changing their attitudes or beliefs, seeking new information that supports one belief over the other, or justifying their actions through rationalization."
    },
    {
      "question": "What are the effects of Cognitive Dissonance?",
      "answer": "Effects of Cognitive Dissonance include decision-making difficulties, reduced self-esteem, emotional discomfort, and behavior change."
    }
  ]
}
        ***
        \n\n
        ***
        {
          "flashcards": [
    {
      "question": "What is a Binary Search Tree (BST)?",
      "answer": "A Binary Search Tree (BST) is a binary tree data structure with two properties: 1. The value of the node to the left is less than the value of the parent node, and 2. The value of the node to the right is greater than or equal to the value of the parent node."
    },
    {
      "question": "List four operations performed on Binary Search Trees.",
      "answer": "Insertion, Deletion, Search, Traversal"
    },
    {
      "question": "What are the three types of tree traversal methods?",
      "answer": "Inorder, Preorder, Postorder"
    },
    {
      "question": "What is the average case complexity of operations performed on Binary Search Trees?",
      "answer": "O(log n)"
    },
    {
      "question": "What is the worst case complexity of operations performed on Binary Search Trees?",
      "answer": "O(n)"
    }
  ]
}
        ***
        He is studying the following material: \n\n
     '''

    for file_path in file_paths:
        texts = file_to_text(file_path, start_page=3)
        if len(texts) != 0:
            for text in texts:
                if len(prompt) > 5000:
                    break
                prompt += f'***{str(text)}*** \n\n'
        else:
            return {"flashcards": []}

    print(prompt)
    answer = generate_text(prompt, engine="gpt-3.5-turbo-16k")
    print(answer)
    flashcard_dict = json.loads(answer)

    return flashcard_dict

    # return flashcards


def generate_answer(question: str, file_paths=[], context: str = None, image: str = None):
    for filename in file_paths:
        load_recommender(filename)

    topn_chunks = []
    for recommender in recommender_list.keys():
        print(f"************Searching in {recommender}***************")
        chunks_found = recommender_list[recommender](question)[:5]
        for chunk in chunks_found:
            print(f"\n*********************{chunk}************************\n")
        topn_chunks.extend(chunks_found)
    prompt = ""
    prompt += 'search results:\n\n'
    for c in topn_chunks:
        prompt += c + '\n\n'
    prompt += f'Context :\n\n{context}'
    prompt += (
        "Instructions: Compose a comprehensive reply to the query using the search results given and the context of the question"
        "Cite each reference using [ Page Number] notation (every result has this number at the beginning). "
        "Citation should be done at the end of each sentence. If the search results mention multiple subjects "
        "with the same name, create separate answers for each. Also, mention the document name in the citation."
        "Answer step-by-step. \n\nQuery: {question}\nAnswer: "
    )

    prompt += f"Query: {question}\nAnswer:"
    answer = generate_text(prompt, image=image, engine="gpt-4-vision-preview")
    return answer
