from sentence_transformers import SentenceTransformer

model = SentenceTransformer("intfloat/multilingual-e5-small")


def embed_passage(text: str) -> list[float]:
    return model.encode("passage: " + text, normalize_embeddings=True).tolist()


def embed_query(text: str) -> list[float]:
    return model.encode("query: " + text, normalize_embeddings=True).tolist()
