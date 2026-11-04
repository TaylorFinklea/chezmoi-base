-- Rex configuration, managed by chezmoi as ~/.config/rex/init.lua.
-- Rex reads this file on the server; it does not watch for changes.
-- Validate a change: `rex config check`   Apply a change: `rex config reload`

-- Keep the ctrl+a prefix used by the tmux config in this repository, so the
-- same muscle memory works in both multiplexers. Prefix sequences consume the
-- prefix key, so bind ctrl+a>ctrl+a to still reach programs that need it.
local prefix = "ctrl+a"

------------------------------------------------------------------ windows ---
rex.bind(prefix .. ">c", "client.tab.new")
rex.bind(prefix .. ">n", "client.tab.next")
rex.bind(prefix .. ">p", "client.tab.previous")
rex.bind(prefix .. ">,", "client.tab.rename")
rex.bind(prefix .. ">shift+x", "client.tab.close")

for index = 1, 9 do
  rex.bind(prefix .. ">" .. index, "client.tab.goto", { index = index })
end

------------------------------------------------------------------- panes ---
-- % and " on a US layout, matching tmux.
rex.bind(prefix .. ">shift+5", "pane.split", { direction = "right" })
rex.bind(prefix .. ">shift+'", "pane.split", { direction = "down" })
rex.bind(prefix .. ">z", "pane.zoom")
rex.bind(prefix .. ">x", "pane.close")
rex.bind(prefix .. ">space", "pane.balance")

-- Vim-style pane focus.
rex.bind(prefix .. ">h", "pane.focus.left")
rex.bind(prefix .. ">j", "pane.focus.down")
rex.bind(prefix .. ">k", "pane.focus.up")
rex.bind(prefix .. ">l", "pane.focus.right")

----------------------------------------------------------------- sessions ---
rex.bind(prefix .. ">s", "session.switch")
rex.bind(prefix .. ">shift+n", "session.new")
rex.bind(prefix .. ">shift+r", "session.rename")

-------------------------------------------------------------------- keys ---
-- Reload this file from inside Rex.
rex.bind(prefix .. ">r", "client.config.reload")
-- Send one literal ctrl+a to the focused terminal.
rex.bind(prefix .. ">ctrl+a", "pane.send_key", { key = "ctrl+a" })
