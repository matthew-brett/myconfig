console.log("Loading custom.js");

Jupyter.notebook.set_autosave_interval(0); // disable autosave

// Configure Jupyter Keymap
require([
  'nbextensions/vim_binding/vim_binding',
  'base/js/namespace',
], function(vim_binding, ns) {
  // Add post callback
  vim_binding.on_ready_callbacks.push(function(){
    var km = ns.keyboard_manager;
    km.edit_shortcuts.add_shortcut('ctrl-o,m', 'vim-binding:change-cell-to-markdown', true);
    km.edit_shortcuts.add_shortcut('ctrl-o,y', 'vim-binding:change-cell-to-code', true);
    km.edit_shortcuts.add_shortcut('ctrl-o,r,r', 'restart-kernel-and-run-all-cells', true);
    // Update Help
    km.edit_shortcuts.events.trigger('rebuild.QuickHelp');
  });
});
