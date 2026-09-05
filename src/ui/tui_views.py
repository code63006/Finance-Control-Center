def render_summary(metrics: dict) -> str:
    return "\n".join(["Finance Controller", "=" * 18, f"accuracy: {metrics['accuracy']:.2%}", f"exceptions: {metrics['exceptions']}"])
