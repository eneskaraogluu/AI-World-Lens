import random
from uuid import UUID
from sqlalchemy.orm import Session
from backend.services.queue_worker import queue_worker
from backend.core.config import settings

class ExperimentManager:
    
    async def run_experiment_async(self, db: Session, experiment_id: UUID, prompt_id: UUID, prompt_text: str, iterations: int, use_mock: bool = False):
        """
        Enqueues tasks for image generation and analysis.
        This allows the API to return immediately while workers process in background.
        """
        generator_type = "mock-generator" if use_mock else {
            "openai": "openai-image", "pollinations": "pollinations-flux"
        }[settings.IMAGE_PROVIDER]
        await queue_worker.register_job(experiment_id, prompt_id, iterations)
        
        # Enqueue N iterations
        for i in range(iterations):
            seed = None if generator_type == "openai-image" else random.randint(1, 999999)
            
            task_data = {
                "prompt_id": prompt_id,
                "prompt_text": prompt_text,
                "experiment_id": experiment_id,
                "generator_type": generator_type,
                "seed": seed,
                "sample_index": i + 1,
            }
            await queue_worker.enqueue_task(task_data)

experiment_manager = ExperimentManager()
