{
  description = "Local Gemma proofreading demo with an 800 ms IBus debounce";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  outputs = { self, nixpkgs }: let
    system = "x86_64-linux";
    pkgs = import nixpkgs { inherit system; };
    python = pkgs.python3.withPackages (p: [ p.pygobject3 ]);
    llama = pkgs.llama-cpp.override { vulkanSupport = true; cudaSupport = false; rocmSupport = false; };
    runtime = [ python pkgs.ibus pkgs.gtk3 pkgs.gobject-introspection llama pkgs.curl ];
  in {
    packages.${system}.default = pkgs.writeShellApplication {
      name = "ibus-proofread";
      runtimeInputs = runtime;
      text = ''
        export GI_TYPELIB_PATH="${pkgs.ibus}/lib/girepository-1.0:${pkgs.gtk3}/lib/girepository-1.0:''${GI_TYPELIB_PATH:-}"
        exec ${python}/bin/python ${./.}/main.py "$@"
      '';
    };
    apps.${system}.default = {
      type = "app";
      program = "${self.packages.${system}.default}/bin/ibus-proofread";
    };
    devShells.${system}.default = pkgs.mkShell {
      packages = runtime ++ [ pkgs.xorg-server pkgs.dbus ];
      GI_TYPELIB_PATH = "${pkgs.ibus}/lib/girepository-1.0:${pkgs.gtk3}/lib/girepository-1.0";
    };
  };
}
