-- Keymaps are automatically loaded on the VeryLazy event
-- Default keymaps that are always set: https://github.com/LazyVim/LazyVim/blob/main/lua/lazyvim/config/keymaps.lua
-- Add any additional keymaps here

local map = vim.keymap.set

-- Next Vim tab
map("n", "<Tab>", "<cmd>tabnext<CR>", { desc = "Next Tab" })
-- Previous Vim tab
map("n", "<S-Tab>", "<cmd>tabprevious<CR>", { desc = "Previous Tab" })
