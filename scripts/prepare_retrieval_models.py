"""One-time download of local embedding and reranking models."""

from fastembed import TextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder


TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
TextCrossEncoder(model_name="Xenova/ms-marco-MiniLM-L-6-v2")
print("Local retrieval models are ready. Runtime can remain offline.")
