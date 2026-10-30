"""One backend interface; heavy imports occur only for a real model load."""
import time
import release


class StubBackend:
    def __init__(self, manifest):
        self.loaded_id = manifest['model_id']; self.runtime_sha256 = manifest['runtime_sha256']; self.calls = 0

    def warmup(self):
        pass

    def generate(self, prompt, limit):
        self.calls += 1
        time.sleep(.01)
        return dict(answer=f'STUB ONLY: {self.loaded_id}', output_tokens=1)


class TransformersBackend:
    def __init__(self, manifest):
        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM
        from pathlib import Path
        self.manifest = manifest; self.runtime = manifest['runtime']
        self.loaded_id = manifest['model_id']; self.runtime_sha256 = manifest['runtime_sha256']; self.calls = 0
        self.torch = torch
        if self.runtime['dtype'] != 'float32' or self.runtime['device'] != 'cpu':
            raise ValueError('This evaluated release requires CPU / float32')
        artifact = release.verify_artifact(manifest)
        torch.manual_seed(self.runtime['generation']['seed'])
        torch.set_num_threads(4)
        self.tokenizer = AutoTokenizer.from_pretrained(str(artifact), local_files_only=True)
        base_dir = Path(manifest.get('base_artifact_uri', artifact))
        self.model = AutoModelForCausalLM.from_pretrained(str(base_dir), dtype=torch.float32, local_files_only=True)
        if manifest['kind'] == 'adapter':
            from peft import PeftModel
            self.model = PeftModel.from_pretrained(self.model, str(artifact), local_files_only=True)
        self.model = self.model.to('cpu').eval()

    def _generate(self, prompt, limit):
        g = self.runtime['generation']
        text = self.tokenizer.apply_chat_template(
            [{'role':'system','content':g['system']},{'role':'user','content':prompt}],
            tokenize=False, add_generation_prompt=True, enable_thinking=g['enable_thinking'])
        batch = self.tokenizer(text, return_tensors='pt')
        if batch['input_ids'].shape[1] > self.runtime['max_input_tokens']:
            raise ValueError('Input token limit exceeded')
        with self.torch.inference_mode():
            out = self.model.generate(**batch, max_new_tokens=limit, do_sample=g['do_sample'],
                pad_token_id=self.tokenizer.pad_token_id or self.tokenizer.eos_token_id)
        tokens = out[0,batch['input_ids'].shape[1]:]
        return dict(answer=self.tokenizer.decode(tokens,skip_special_tokens=True),output_tokens=len(tokens))

    def warmup(self):
        self._generate('Напиши стихотворение.', self.runtime['generation']['max_new_tokens'])

    def generate(self,prompt,limit):
        # Counting starts after validation in the HTTP layer; only this backend computes.
        result = self._generate(prompt,limit)
        self.calls += 1
        return result
