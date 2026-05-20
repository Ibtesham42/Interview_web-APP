from typing import List, Dict, Any
from openai import OpenAI
from app.config import get_settings
from app.supabase_client import get_supabase

class MLQuestionRetriever:
    """RAG-based retrieval of ML questions based on candidate's field."""

    def __init__(self):
        from app.config import get_settings
        settings = get_settings()
        self.client = OpenAI(api_key=settings.openai_api_key)
        self._supabase = None

    @property
    def supabase(self):
        if self._supabase is None:
            self._supabase = get_supabase()
        return self._supabase

    async def get_embedding(self, text: str) -> List[float]:
        """Get embedding for text using OpenAI."""
        response = self.client.embeddings.create(
            model="text-embedding-3-small",
            input=text
        )
        return response.data[0].embedding

    async def retrieve_questions(
        self,
        field: str,
        category: str = None,
        limit: int = 8
    ) -> List[Dict[str, Any]]:
        """Retrieve ML questions based on candidate's field specialization."""
        # Get candidate's primary topics based on field
        field_topics = {
            "nlp": ["nlp", "transformers", "language models", "text", "tokenization", "embeddings", "attention"],
            "cv": ["computer vision", "cnn", "object detection", "image", "segmentation", "vision"],
            "ml": ["machine learning", "neural networks", "optimization", "gradient descent", "regularization"],
            "research": ["research", "papers", "publications", "state of the art"]
        }

        topics = field_topics.get(field.lower(), field_topics["ml"])

        # Get questions from database
        if category:
            result = self.supabase.table("ml_questions").select("*").eq("category", category).limit(limit * 2).execute()
        else:
            result = self.supabase.table("ml_questions").select("*").limit(limit * 3).execute()

        questions = result.data if result.data else []

        # Score questions by relevance to field
        scored_questions = []
        for q in questions:
            score = 0
            q_text = (q.get("question", "") + " " + q.get("answer", "")).lower()
            for topic in topics:
                if topic.lower() in q_text:
                    score += 1
            scored_questions.append((score, q))

        # Sort by score and take top N
        scored_questions.sort(key=lambda x: x[0], reverse=True)
        selected = [q for _, q in scored_questions[:limit]]

        # If not enough questions, use defaults
        if len(selected) < limit:
            selected.extend(self._get_default_questions(field, limit - len(selected)))

        return selected[:limit]

    def _get_default_questions(self, field: str, count: int) -> List[Dict[str, Any]]:
        """Get default ML questions if database is empty."""
        defaults = {
            "nlp": [
                {"category": "fundamentals", "question": "What is the attention mechanism in transformers?", "answer": "Attention allows models to weigh the importance of different parts of the input when processing each element. It computes a weighted sum of values based on similarity between queries and keys."},
                {"category": "nlp", "question": "What is the difference between GPT and BERT?", "answer": "GPT uses causal (unidirectional) attention for generation tasks. BERT uses bidirectional attention allowing it to understand context from both sides for understanding tasks."},
                {"category": "fundamentals", "question": "What is gradient descent?", "answer": "Gradient descent is an optimization algorithm that minimizes a function by iteratively moving in the direction of steepest descent as defined by the negative gradient."},
            ],
            "cv": [
                {"category": "cv", "question": "Why do we use convolutions instead of fully connected layers for images?", "answer": "Convolutions preserve spatial information and provide translation invariance. They also have fewer parameters than FC layers and capture local patterns effectively."},
                {"category": "cv", "question": "What is max pooling and why do we use it?", "answer": "Max pooling reduces spatial dimensions by taking the maximum value in each window. It provides translation invariance and reduces computation."},
                {"category": "fundamentals", "question": "What is gradient descent?", "answer": "Gradient descent is an optimization algorithm that minimizes a function by iteratively moving in the direction of steepest descent."},
            ],
            "ml": [
                {"category": "fundamentals", "question": "What is the bias-variance tradeoff?", "answer": "High bias causes underfitting (too simple), high variance causes overfitting (too complex). The goal is to find the right balance."},
                {"category": "fundamentals", "question": "What is gradient descent?", "answer": "Gradient descent is an optimization algorithm that minimizes a function by iteratively moving in the direction of steepest descent."},
                {"category": "fundamentals", "question": "What is regularization and why do we use it?", "answer": "Regularization discourages learning overly complex models to prevent overfitting. Examples include L1 (Lasso) and L2 (Ridge)."},
            ]
        }

        return defaults.get(field, defaults["ml"])[:count]


async def seed_ml_questions():
    """Seed the database with ML questions from the MLQuestions repo."""
    supabase = get_supabase()
    client = OpenAI(api_key=settings.openai_api_key)

    questions = [
        # Fundamentals
        {"category": "fundamentals", "question": "What's the trade-off between bias and variance?", "answer": "High bias means underfitting (model too simple), high variance means overfitting (model too complex for data). The goal is to find the right balance."},
        {"category": "fundamentals", "question": "What is gradient descent?", "answer": "Gradient descent is an optimization algorithm used to find the values of parameters that minimize a cost function. It iteratively updates parameters in the direction of steepest descent."},
        {"category": "fundamentals", "question": "Explain overfitting and underfitting and how to combat them.", "answer": "Underfitting: model too simple to capture patterns. Overfitting: model too complex, memorizes noise. Combat with regularization, cross-validation, more data."},
        {"category": "fundamentals", "question": "How do you combat the curse of dimensionality?", "answer": "Feature selection, PCA, multidimensional scaling, locally linear embedding. Reduce features while preserving important information."},
        {"category": "fundamentals", "question": "What is regularization, why do we use it, and give examples?", "answer": "Regularization discourages learning a more complex model to prevent overfitting. Examples: Ridge (L2), Lasso (L1)."},
        {"category": "fundamentals", "question": "Explain Principal Component Analysis (PCA).", "answer": "PCA is a dimensionality reduction technique that identifies directions of maximum variance in data and projects onto a lower-dimensional subspace."},
        {"category": "fundamentals", "question": "What is data normalization and why do we need it?", "answer": "Rescaling values to fit a specific range (subtract mean, divide by std). Ensures better convergence during backpropagation."},
        {"category": "fundamentals", "question": "Why do we need a validation set and test set?", "answer": "Training set fits parameters. Validation set measures generalization and tunes hyperparameters. Test set evaluates final model performance."},

        # Neural Networks
        {"category": "neural_networks", "question": "Why is ReLU better than Sigmoid in Neural Networks?", "answer": "ReLU is computationally efficient, has reduced vanishing gradient, and produces sparsity. Sigmoid saturates quickly causing gradient issues."},
        {"category": "neural_networks", "question": "Why do we use convolutions for images rather than just FC layers?", "answer": "Convolutions preserve spatial information, provide translation invariance, and have fewer parameters than fully connected layers."},
        {"category": "neural_networks", "question": "What makes CNNs translation invariant?", "answer": "Each convolution kernel acts as a filter/detector applied in a sliding window fashion across the entire image."},
        {"category": "neural_networks", "question": "Why do we have max-pooling in classification CNNs?", "answer": "Max-pooling reduces spatial dimensions, reduces computation, provides translation invariance, and retains maximum activation."},
        {"category": "neural_networks", "question": "What is the significance of Residual Networks?", "answer": "Residual connections allow direct feature access from previous layers, making information propagation easier and enabling training of very deep networks."},
        {"category": "neural_networks", "question": "What is batch normalization and why does it work?", "answer": "Normalizing inputs of each layer to have zero mean and unit variance. Stabilizes training by reducing internal covariate shift."},
        {"category": "neural_networks", "question": "What is vanishing gradient?", "answer": "As gradients propagate back through deep networks, they can become very small, making lower layers learn slowly. Batch norm, residual connections, and ReLU help."},
        {"category": "neural_networks", "question": "Define LSTM.", "answer": "Long Short Term Memory networks are RNN variants designed to address long-term dependencies through gating mechanisms."},
        {"category": "neural_networks", "question": "What are the key components of LSTM?", "answer": "Forget gate, input gate, output gate, cell state, and tanh activation functions."},
        {"category": "neural_networks", "question": "What is Autoencoder? Name a few applications.", "answer": "Learns compressed representation of data. Applications: data denoising, dimensionality reduction, image reconstruction."},

        # Evaluation Metrics
        {"category": "evaluation", "question": "What is Precision?", "answer": "Fraction of relevant instances among retrieved instances. Precision = TP / (TP + FP)"},
        {"category": "evaluation", "question": "What is Recall?", "answer": "Fraction of relevant instances retrieved. Recall = TP / (TP + FN)"},
        {"category": "evaluation", "question": "Define F1-score.", "answer": "Harmonic mean of precision and recall. F1 = 2 * (precision * recall) / (precision + recall)"},
        {"category": "evaluation", "question": "Explain how a ROC curve works.", "answer": "Plots true positive rate vs false positive rate at various thresholds. Shows tradeoff between sensitivity and specificity."},
        {"category": "evaluation", "question": "What's the difference between Type I and Type II error?", "answer": "Type I: False positive (reject true null). Type II: False negative (fail to reject false null)."},

        # Ensembles
        {"category": "ensembles", "question": "Why do ensembles typically have higher scores than individual models?", "answer": "Models make different errors that can compensate each other. Combining predictions reduces overall error."},
        {"category": "ensembles", "question": "What is an imbalanced dataset? List some ways to deal with it.", "answer": "Different proportions of target categories. Solutions: oversampling, undersampling, data augmentation, appropriate metrics (F1, precision-recall)."},
        {"category": "ensembles", "question": "What's the difference between boosting and bagging?", "answer": "Bagging: bootstrap samples, train independently, average predictions. Boosting: sequential training, focus on misclassified instances."},
        {"category": "ensembles", "question": "What are the components of GAN?", "answer": "Generator: creates fake samples. Discriminator: distinguishes real from fake. They compete in a minimax game."},

        # NLP Specific
        {"category": "nlp", "question": "What is the attention mechanism?", "answer": "Allows model to focus on relevant parts of input when generating output. Computes weighted sum of values based on query-key similarity."},
        {"category": "nlp", "question": "What is the difference between RNN and Transformer?", "answer": "RNN processes sequentially, suffers from long-range dependencies. Transformer processes all positions simultaneously with self-attention."},
        {"category": "nlp", "question": "What is tokenization?", "answer": "Splitting text into smaller units (words, subwords, characters). Enables models to process text numerically."},
        {"category": "nlp", "question": "What is RAG (Retrieval-Augmented Generation)?", "answer": "Combines retrieval from external knowledge base with LLM generation. Improves factual accuracy and allows up-to-date information."},

        # Computer Vision Specific
        {"category": "cv", "question": "What is Non-Maximum Suppression?", "answer": "Removes overlapping bounding boxes by keeping only the one with highest confidence score. Used in object detection."},
        {"category": "cv", "question": "What is the difference between semantic segmentation and object detection?", "answer": "Semantic segmentation: classifies each pixel. Object detection: finds bounding boxes and labels objects."},
        {"category": "cv", "question": "What is transfer learning in CV?", "answer": "Using a model pretrained on large dataset (ImageNet) and fine-tuning on your smaller dataset. Saves training time and improves performance."},
    ]

    # Insert questions
    for q in questions:
        # Generate embedding
        embedding = await MLQuestionRetriever().get_embedding(q["question"])

        supabase.table("ml_questions").insert({
            "category": q["category"],
            "question": q["question"],
            "answer": q["answer"],
            "embedding": embedding
        }).execute()

    return len(questions)
