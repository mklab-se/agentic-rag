// Lets prompt agents reach the knowledge base MCP endpoint as the project's managed identity.
param accountName string
param projectName string
param searchEndpoint string
param knowledgeBaseName string
param connectionName string = 'voltrieve-kb-mcp'

resource account 'Microsoft.CognitiveServices/accounts@2026-09-15-preview' existing = {
  name: accountName
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2026-09-15-preview' existing = {
  parent: account
  name: projectName
}

resource connection 'Microsoft.CognitiveServices/accounts/projects/connections@2026-09-15-preview' = {
  parent: project
  name: connectionName
  properties: {
    authType: 'ProjectManagedIdentity'
    category: 'RemoteTool'
    target: '${searchEndpoint}/knowledgebases/${knowledgeBaseName}/mcp?api-version=2026-08-01-preview'
    isSharedToAll: true
    audience: 'https://search.azure.com/'
    metadata: { ApiType: 'Azure' }
  }
}

output name string = connection.name
