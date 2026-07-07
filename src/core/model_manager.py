from src.core.config import config

class ModelManager:
    def __init__(self, config):
        self.config = config
    
    def map_claude_model_to_openai(self, claude_model: str) -> str:
        """Map Claude model names to OpenAI model names based on BIG/SMALL pattern"""
        # Provider-specific paths (e.g., accounts/fireworks/models/...) pass through as-is
        if claude_model.startswith("accounts/"):
            return claude_model

        # If it's already an OpenAI model, return as-is
        if claude_model.startswith("gpt-") or claude_model.startswith("o1-"):
            return claude_model

        # If it's other supported models (ARK/Doubao), return as-is
        if claude_model.startswith("ep-") or claude_model.startswith("doubao-"):
            return claude_model

        # Auto-prefix bare deepseek model names for Fireworks-style paths
        if claude_model.startswith("deepseek-"):
            if self.config.model_prefix:
                return f"{self.config.model_prefix}{claude_model}"
            return claude_model

        # Map based on model naming patterns
        model_lower = claude_model.lower()
        if 'haiku' in model_lower:
            return self.config.small_model
        elif 'sonnet' in model_lower:
            return self.config.middle_model
        elif 'opus' in model_lower:
            return self.config.big_model
        else:
            # Default to big model for unknown models
            return self.config.big_model

model_manager = ModelManager(config)