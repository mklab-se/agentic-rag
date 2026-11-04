// Reads the image a Container App currently runs, so a later `azd provision` keeps what
// `azd deploy` shipped. A file cannot declare and read the same name, hence this module.
// Only deploy it when the app exists. The API uses it too.
param name string

resource app 'Microsoft.App/containerApps@2026-07-01' existing = {
  name: name
}

output image string = app.properties.template.containers[0].image
