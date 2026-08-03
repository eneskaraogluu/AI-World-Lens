from scripts.load_prompts import load_prompts, project_root


if __name__ == "__main__":
    import os

    load_prompts(os.path.join(project_root, "data", "prompts.json"))
