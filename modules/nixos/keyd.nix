{
  services.keyd = {
    enable = true;

    keyboards.default = {
      ids = [ "*" ];

      settings = {
        main = {
          capslock = "overloadt(150, esc, leftmeta)";

          a = "overloadt(150, a, leftshift)";
          s = "overloadt(150, s, leftcontrol)";
          d = "overloadt(150, d, leftalt)";
          f = "overloadt(150, f, leftmeta)";

          j = "overloadt(150, j, rightmeta)";
          k = "overloadt(150, k, rightalt)";
          l = "overloadt(150, l, rightcontrol)";
          ";" = "overloadt(150, ;, rightshift)";
        };
      };
    };
  };
}
