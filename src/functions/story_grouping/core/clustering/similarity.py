"""Similarity calculations and centroid computation."""

import logging
from typing import List
import numpy as np

logger = logging.getLogger(__name__)


def calculate_cosine_similarity(vector_a: List[float], vector_b: List[float]) -> float:
    """
    Calculate cosine similarity between two vectors.
    
    Cosine similarity measures the cosine of the angle between two vectors,
    ranging from -1 (opposite) to 1 (identical). For normalized embeddings,
    this is equivalent to the dot product.
    
    Args:
        vector_a: First embedding vector
        vector_b: Second embedding vector
        
    Returns:
        Cosine similarity score (0 to 1 for normalized vectors)
        
    Raises:
        ValueError: If vectors have different dimensions or are empty
    """
    if not vector_a or not vector_b:
        raise ValueError("Vectors cannot be empty")
    
    if len(vector_a) != len(vector_b):
        raise ValueError(
            f"Vectors must have same dimension "
            f"({len(vector_a)} vs {len(vector_b)})"
        )
    
    # Convert to numpy arrays for efficient computation
    a = np.array(vector_a, dtype=np.float32)
    b = np.array(vector_b, dtype=np.float32)
    
    # Calculate dot product
    dot_product = np.dot(a, b)
    
    # Calculate magnitudes
    magnitude_a = np.linalg.norm(a)
    magnitude_b = np.linalg.norm(b)
    
    # Avoid division by zero
    if magnitude_a == 0 or magnitude_b == 0:
        logger.warning("Zero magnitude vector encountered")
        return 0.0
    
    # Cosine similarity
    similarity = dot_product / (magnitude_a * magnitude_b)
    
    # Clamp to [0, 1] range (handles floating point errors)
    return float(max(0.0, min(1.0, similarity)))


def calculate_centroid(embeddings: List[List[float]]) -> List[float]:
    """
    Calculate the centroid (mean) of multiple embedding vectors.
    
    The centroid is the arithmetic mean of all vectors, representing the
    "average" or "center" of the group.
    
    Args:
        embeddings: List of embedding vectors
        
    Returns:
        Centroid vector (same dimension as input vectors)
        
    Raises:
        ValueError: If embeddings list is empty or vectors have different dimensions
    """
    if not embeddings:
        raise ValueError("Embeddings list cannot be empty")
    
    # Check all vectors have same dimension
    dimensions = len(embeddings[0])
    for i, emb in enumerate(embeddings[1:], start=1):
        if len(emb) != dimensions:
            raise ValueError(
                f"All embeddings must have same dimension. "
                f"First: {dimensions}, embedding {i}: {len(emb)}"
            )
    
    # Convert to numpy array for efficient computation
    embeddings_array = np.array(embeddings, dtype=np.float32)
    
    # Calculate mean along axis 0 (average across all vectors)
    centroid = np.mean(embeddings_array, axis=0)
    
    # Normalize the centroid (optional but recommended for cosine similarity)
    norm = np.linalg.norm(centroid)
    if norm > 0:
        centroid = centroid / norm
    
    return centroid.tolist()


def calculate_pairwise_similarities(
    embeddings: List[List[float]],
) -> np.ndarray:
    """
    Calculate pairwise cosine similarities between all embeddings.
    
    Args:
        embeddings: List of embedding vectors
        
    Returns:
        NxN numpy array where element [i,j] is the similarity between
        embeddings[i] and embeddings[j]
    """
    if not embeddings:
        return np.array([])
    
    n = len(embeddings)
    embeddings_array = np.array(embeddings, dtype=np.float32)
    
    # Normalize embeddings
    norms = np.linalg.norm(embeddings_array, axis=1, keepdims=True)
    norms[norms == 0] = 1  # Avoid division by zero
    normalized = embeddings_array / norms
    
    # Compute pairwise similarities via matrix multiplication
    # This is more efficient than calculating each pair individually
    similarities = np.dot(normalized, normalized.T)
    
    # Clamp to [0, 1] range
    similarities = np.clip(similarities, 0.0, 1.0)
    
    return similarities


def find_most_similar(
    query_vector: List[float],
    candidate_vectors: List[List[float]],
    threshold: float = 0.0,
) -> tuple[int, float]:
    """
    Find the most similar vector from candidates.
    
    Args:
        query_vector: Vector to compare against
        candidate_vectors: List of candidate vectors
        threshold: Minimum similarity threshold (0 to 1)
        
    Returns:
        Tuple of (index, similarity) for most similar candidate,
        or (-1, 0.0) if no candidate meets threshold
    """
    if not candidate_vectors:
        return (-1, 0.0)
    
    best_idx = -1
    best_similarity = threshold
    
    for idx, candidate in enumerate(candidate_vectors):
        similarity = calculate_cosine_similarity(query_vector, candidate)
        
        if similarity > best_similarity:
            best_similarity = similarity
            best_idx = idx
    
    return (best_idx, best_similarity)


def calculate_intra_cluster_similarity(embeddings: List[List[float]]) -> float:
    """
    Calculate average pairwise similarity within a cluster.
    
    This measures how "tight" or cohesive a cluster is. Higher values
    indicate more similar members.
    
    Args:
        embeddings: List of embedding vectors in the cluster
        
    Returns:
        Average pairwise similarity (0 to 1)
    """
    if len(embeddings) < 2:
        return 1.0  # Single item is perfectly similar to itself
    
    similarities = calculate_pairwise_similarities(embeddings)
    
    # Get upper triangle (excluding diagonal) to avoid counting each pair twice
    n = len(embeddings)
    upper_triangle = similarities[np.triu_indices(n, k=1)]
    
    return float(np.mean(upper_triangle))
