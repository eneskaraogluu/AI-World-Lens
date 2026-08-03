import asyncio
from unittest.mock import AsyncMock, patch

from backend.services.mock_generator import MockGenerator


async def exercise_mock_generator():
    generator = MockGenerator()
    assert generator.model_name == "mock-generator"
    assert generator.model_version == "1.0"
    with patch("backend.services.mock_generator.random.uniform", return_value=0), patch(
        "backend.services.mock_generator.asyncio.sleep", new=AsyncMock()
    ) as fake_sleep:
        image_reference, duration_ms, error = await generator.generate_image("A teacher", 7)
    fake_sleep.assert_awaited_once_with(0)
    assert image_reference.endswith("/17.jpg")
    assert isinstance(duration_ms, int) and duration_ms >= 0
    assert error is None


if __name__ == "__main__":
    asyncio.run(exercise_mock_generator())
    print("MOCK GENERATOR: PASS")
