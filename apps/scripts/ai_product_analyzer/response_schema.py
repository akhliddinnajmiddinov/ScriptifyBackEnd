schema = {
    "name": "product_analysis",
    "schema": {
        "type": "object",
        "properties": {
            "ai_title": {"type": "string"},
            "ai_confidence": {"type": "number"},
            "ai_confidence_reason": {"type": "string"},
            "title_match_confidence": {"type": "number"},
            "title_match_confidence_reason": {"type": "string"},
            "products": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "brand": {"type": "string"},
                        "model": {"type": "string"},
                        "quantity": {"type": "number"},
                        "confidence": {"type": "number"},
                        "is_original": {"type": "boolean"},
                        "original_verification_reason": {"type": "string"}
                    },
                    "required": ["title"]
                }
            }
        },
        "required": [
            "ai_title",
            "ai_confidence",
            "ai_confidence_reason",
            "title_match_confidence",
            "title_match_confidence_reason",
            "products"
        ]
    }
}