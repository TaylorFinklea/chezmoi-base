return {
  "nvim-neo-tree/neo-tree.nvim",
  opts = {
    window = {
      position = "left",
      width = 30,
    },
    filesystem = {
      follow_current_file = {
        enabled = true,
      },
      hijack_netrw_behavior = "open_default",
    },
  },
  keys = {
    -- Toggle focus between explorer and editor (doesn't close)
    {
      "<leader>e",
      function()
        if vim.bo.filetype == "neo-tree" then
          vim.cmd.wincmd("p") -- Jump to previous window
        else
          vim.cmd("Neotree focus")
        end
      end,
      desc = "Focus File Explorer",
    },
    -- Close the explorer
    { "<leader>E", "<cmd>Neotree close<CR>", desc = "Close File Explorer" },
  },
}
