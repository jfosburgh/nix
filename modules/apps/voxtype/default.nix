{...}: {
  # Opt in per host; no Home Manager profile or keyboard-device permissions needed.
  flake.nixosModules.voxtype = {
    pkgs,
    lib,
    ...
  }: let
    # The regular Parakeet TDT exports lack the cache-aware streaming graphs
    # and tokenizer. Use Voxtype's recommended unified English streaming model.
    revision = "09e9060322d99c5f070010724786e6ee090fd51d";
    modelFiles = {
      "encoder.onnx" = "50083dd0b2af503b87ea8fcf9fd7d7dc15dda3130e4113017c8b37ed00418ba4";
      "encoder.onnx.data" = "c054b2932ee13aa39ed84982a399822f3193311fb6fd8e1e204566722614bd87";
      "decoder_joint.onnx" = "64648c91935ea4819e9c31ea8a20f011d3b1c960be3861cb8bc74df0259cd998";
      "tokenizer.model" = "07d4e5a63840a53ab2d4d106d2874768143fb3fbdd47938b3910d2da05bfb0a9";
      "vocab.txt" = "sha256-rmHJt0PLR8BM5vsTBEQhBkbtD0DJU8d+4YVRhZYK+U8=";
    };
    model = pkgs.linkFarm "parakeet-unified-en-0.6b" (lib.mapAttrsToList (name: sha256: {
        inherit name;
        path = pkgs.fetchurl {
          url = "https://huggingface.co/bobNight/parakeet-unified-en-0.6b-onnx/resolve/${revision}/${name}";
          inherit sha256;
        };
      })
      modelFiles);
    routedWtype = pkgs.writeShellApplication {
      name = "wtype";
      runtimeInputs = [pkgs.tmux pkgs.util-linux pkgs.coreutils];
      text =
        ''
          export VOXTYPE_REAL_WTYPE=${lib.getExe pkgs.wtype}
        ''
        + builtins.readFile ./route-wtype.sh;
    };
    routedNotify = pkgs.writeShellApplication {
      name = "notify-send";
      runtimeInputs = [pkgs.coreutils];
      text =
        ''
          export VOXTYPE_REAL_NOTIFY_SEND=${lib.getExe' pkgs.libnotify "notify-send"}
        ''
        + builtins.readFile ./route-notify-send.sh;
    };
    quickshellFiles = pkgs.runCommand "voxtype-quickshell" {} ''
      cp -r ${pkgs.voxtype-onnx.src}/quickshell "$out"
      # Streaming is microphone dictation too, not speaker/audio playback.
      chmod u+w "$out/OsdSurface.qml"
      substituteInPlace "$out/OsdSurface.qml" \
        --replace-fail '"󰜟"' '"󰍬"'
    '';
    # Rewrap the cached ONNX executable instead of recompiling it. All live
    # output (including partial-text corrections) passes through the router.
    package = pkgs.symlinkJoin {
      name = "voxtype-routed";
      paths = [pkgs.voxtype-onnx];
      nativeBuildInputs = [pkgs.makeWrapper];
      postBuild = ''
        rm "$out/bin/voxtype"
        makeWrapper ${pkgs.voxtype-onnx}/bin/.voxtype-wrapped "$out/bin/voxtype" \
          --set ORT_DYLIB_PATH ${lib.getLib pkgs.onnxruntime}/lib/libonnxruntime.so \
          --prefix LD_LIBRARY_PATH : ${lib.getLib pkgs.onnxruntime}/lib \
          --prefix PATH : ${lib.makeBinPath [routedWtype routedNotify pkgs.wl-clipboard pkgs.which pkgs.voxtype-onnx pkgs.quickshell]}
      '';
      meta.mainProgram = "voxtype";
    };
    dictationTarget = pkgs.writeShellApplication {
      name = "voxtype-dictate";
      runtimeInputs = [package pkgs.jq pkgs.util-linux pkgs.coreutils];
      text = builtins.readFile ./dictation-target.sh;
    };
    submitPi = pkgs.writeShellApplication {
      name = "voxtype-submit-pi";
      runtimeInputs = [pkgs.voxtype-onnx pkgs.tmux pkgs.jq pkgs.coreutils];
      text = builtins.readFile ./submit-pi.sh;
    };
    settings = (pkgs.formats.toml {}).generate "voxtype-config.toml" {
      engine = "parakeet";
      state_file = "auto";
      hotkey = {
        enabled = false;
        # Live output and held PTT keys interfere on Hyprland. The compositor
        # calls record toggle instead; no key needs to stay down while typing.
        mode = "toggle";
      };
      audio = {
        device = "default";
        sample_rate = 16000;
        # Safety timeout, not a streaming chunk size. Avoid the old 60s cutoff.
        max_duration_secs = 300;
      };
      parakeet = {
        model = "${model}";
        streaming = true;
        on_demand_loading = false;
        # Voxtype 1.0.1 defaults are not aligned to the model's 8-frame
        # subsampling. Use parakeet-rs 0.3.5's valid native defaults instead.
        streaming_chunk_secs = 0.56;
        streaming_left_context_secs = 5.6;
        streaming_right_context_secs = 0.56;
      };
      osd = {
        enabled = true;
        frontend = "quickshell";
        palette = "fallback";
        layout = "minimal";
        position = "top-center";
        top_margin = 0.08;
        frame = {
          border = "none";
          glow = false;
          halo = false;
        };
        visual.layers = [
          {
            type = "waveform";
            source = "peak";
            color = "accent";
          }
        ];
      };
      output = {
        mode = "type";
        driver_order = ["wtype" "clipboard"];
        fallback_to_clipboard = true;
        auto_submit = false; # Never send Enter to the active application.
        post_output_command = lib.getExe submitPi;
        notification = {
          # The state-driven waveform OSD replaces recording notifications.
          on_recording_start = false;
          on_recording_stop = false;
          on_transcription = false;
        };
      };
    };
  in {
    environment.systemPackages = [package dictationTarget];
    environment.etc."voxtype/config.toml".source = settings;
    environment.etc."voxtype/hyprland.lua".source = ./hyprland.lua;

    # UWSM imports the Wayland environment before starting this target. Don't
    # load a streaming model in work's GNOME session, which has no binding.
    systemd.user.services.voxtype = {
      description = "Local live speech transcription";
      wantedBy = ["graphical-session.target"];
      partOf = ["graphical-session.target"];
      after = ["graphical-session.target"];
      unitConfig.ConditionEnvironment = "HYPRLAND_INSTANCE_SIGNATURE";
      environment = {
        # The supervised OSD child doesn't inherit the daemon's --config flag.
        VOXTYPE_CONFIG = settings;
        VOXTYPE_OSD_QML_PATH = quickshellFiles;
      };
      serviceConfig = {
        ExecStartPre = "${lib.getExe' pkgs.coreutils "rm"} -f %t/voxtype-pi-target %t/voxtype-pi-submit %t/voxtype-pi-chars %t/voxtype-pi-failed";
        ExecStart = "${lib.getExe package} --config ${settings} daemon";
        Restart = "on-failure";
        RestartSec = 5;
      };
    };
  };
}
