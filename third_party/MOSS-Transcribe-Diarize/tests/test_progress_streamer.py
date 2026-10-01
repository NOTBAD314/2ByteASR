import unittest

import torch

from moss_transcribe_diarize.app.model_runner import generation_progress
from moss_transcribe_diarize.inference_utils import ProgressStreamer


class ProgressStreamerTest(unittest.TestCase):
    def test_counts_generated_tokens_after_prompt_prefill(self):
        counts = []
        streamer = ProgressStreamer(counts.append)

        streamer.put(torch.tensor([[1, 2, 3]]))
        streamer.put(torch.tensor([4]))
        streamer.put(torch.tensor([[5, 6]]))
        streamer.end()

        self.assertEqual(counts, [1, 3])
        self.assertEqual(streamer.generated_tokens, 3)

    def test_generation_progress_mapping(self):
        self.assertEqual(generation_progress(0, 100), 0.25)
        self.assertAlmostEqual(generation_progress(50, 100), 0.55)
        self.assertEqual(generation_progress(100, 100), 0.85)
        self.assertEqual(generation_progress(150, 100), 0.85)
        self.assertEqual(generation_progress(10, None), 0.25)


if __name__ == "__main__":
    unittest.main()
