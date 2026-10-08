# Editable-file task sidecars

The controller creates one sidecar per task whose editable target cannot safely contain an inline comment, or whose deletion would make an inline marker unsuitable. The task's anchor path still identifies a declared write file.

Sidecars do not authorize changes to frozen or protected files. The controller removes a sidecar marker only after canonical task completion, and checks orphaned/misplaced markers.
