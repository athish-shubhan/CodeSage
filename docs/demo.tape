Output docs/demo.gif
Set Shell "bash"
Set FontSize 16
Set Width 1200
Set Height 720
Set Padding 16
Set Framerate 15
Set Theme "Catppuccin Mocha"
Set TypingSpeed 40ms

Hide
Type "export PS1='$ ' && clear"
Enter
Sleep 1s
Show

Type "make demo"
Sleep 800ms
Enter
Wait+Screen@120s /time to first token/
Sleep 6s
