// pi-vimmode global keybindings — ~/.pi/agent/pi-vimmode.config.js
// Runs as trusted local code with Pi process privileges. Keymaps only:
// no raw object export, no arbitrary custom actions (see pi-vimmode
// docs/settings.md for boundaries and the full action reference).
// Syntax: vim.keymap.set(mode, lhs, rhs) — modes "n" / "i" / "v";
// rhs is a vim.prompt.* helper or a key-sequence string (":vimdoctor<CR>").
// Apply changes inside pi with: /vimmode reload
export default (vim) => {
	// Examples — uncomment to use:
	// vim.keymap.set("i", "<A-w>", vim.prompt.deleteWordBackward());
	// vim.keymap.set("n", "zq", vim.prompt.reflow({ width: 88 }));
	// vim.keymap.set("n", "ZD", ":vimdoctor<CR>");
};
