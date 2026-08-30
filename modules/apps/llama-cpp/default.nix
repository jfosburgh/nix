{ ... }: {
	flake.nixosModules.llama-cpp = { pkgs, ... }: let
		llama-cpp-vulkan = pkgs.llama-cpp.override {
			vulkanSupport = true;
		};

		maxModels = 1;
		reasoningBudget = 4096;
		modelsPreset = pkgs.writeText "llama-cpp-presets.ini" ''
version = 1

[qwen38-q3]
n-gpu-layers = 99
ctx-size = 131072
flash-attn = on
mmproj-auto = off
repeat-penalty = 1.05
repeat-last-n = 512
hf-repo = unsloth/Qwen3.8-27B-GGUF:UD-IQ3_XXS
temp = 1.0
top-p = 0.95
top-k = 20
cache-type-k = q5_1
cache-type-v = q5_1
spec-type = draft-mtp,ngram-mod
spec-draft-n-max = 2
parallel = 1
		'';
	in {
		services.llama-cpp = {
			enable = true;
			package = llama-cpp-vulkan;
			settings.models-preset = "${modelsPreset}";
			settings.host = "0.0.0.0";
			openFirewall = true;
		};

		systemd.services.llama-cpp.serviceConfig.Environment = [
			"XDG_CACHE_HOME=/var/cache/llama-cpp"
		];

		environment.systemPackages = [ llama-cpp-vulkan ];
	};
}
