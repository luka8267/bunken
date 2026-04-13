Office.onReady(function () {
  if (Office.actions && Office.actions.associate) {
    Office.actions.associate("noop", function () {});
  }
});
