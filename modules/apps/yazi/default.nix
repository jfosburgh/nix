{...}: {
  flake.homeModules.yazi = {pkgs, ...}: {
    home.packages = [pkgs.exiftool];

    programs.yazi = {
      enable = true;
      enableZshIntegration = true;

      plugins = {
        inherit (pkgs.yaziPlugins) mount;
        raw = ./raw.yazi;
      };

      # Camera RAW formats embed a JPEG that exiftool can pull out (see
      # raw.yazi/init.lua) -- the built-in image previewer can't decode the
      # RAW data itself. Extensions cover the common Canon/Nikon/Sony/
      # Olympus/Fujifilm/Panasonic/Pentax/Adobe/Samsung/Sigma/Leica/Kodak
      # formats, upper and lower case.
      settings.plugin.prepend_previewers = [
        {
          url = "*.{orf,ORF,cr2,CR2,cr3,CR3,crw,CRW,nef,NEF,nrw,NRW,arw,ARW,sr2,SR2,srf,SRF,raf,RAF,rw2,RW2,pef,PEF,dng,DNG,srw,SRW,x3f,X3F,rwl,RWL,dcr,DCR,kdc,KDC}";
          run = "raw";
        }
      ];

      keymap.mgr.prepend_keymap = [
        {
          on = ["M"];
          run = "plugin mount";
          desc = "Mount/unmount/jump to a device";
        }
      ];
    };
  };
}
