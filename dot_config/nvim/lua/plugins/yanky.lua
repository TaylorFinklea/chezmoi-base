return {
  {
    "gbprod/yanky.nvim",
    opts = function(_, opts)
      opts.system_clipboard = opts.system_clipboard or {}
      if vim.env.TMUX then
        opts.system_clipboard.sync_with_ring = false
      end
    end,
  },
}
