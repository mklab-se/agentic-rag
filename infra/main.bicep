targetScope = 'subscription'

@minLength(1)
@maxLength(22)
@description('Name of the azd environment, used in resource names and tags.')
param environmentName string

@description('Primary Azure region.')
param location string = 'swedencentral'

@description('Region for Azure AI Search. Sweden Central and West Europe cannot create new search services.')
param searchLocation string = 'francecentral'

@description('Object id of the deployer (AZURE_PRINCIPAL_ID), granted data-plane roles.')
param principalId string

// Empty defaults because azd checks required parameters before the preprovision
// hook that produces these values has run. The hook fails hard, so a real
// deployment always has them.
param tenantId string = ''
param dealerClientId string = ''
param apiClientId string = ''
@description('True when the API Container App already exists (azd sets SERVICE_API_RESOURCE_EXISTS), so provision keeps its deployed image.')
param apiExists bool = false
@description('West Europe rejected new Static Web Apps; East US 2 holds only metadata, content is served globally.')
param webLocation string = 'eastus2'
@description('True when the dealer Container App already exists (azd sets SERVICE_DEALER_RESOURCE_EXISTS), so provision keeps its deployed image.')
param dealerExists bool = false
@description('Principal id of the hosted agent identity (HOSTED_AGENT_PRINCIPAL_ID, set by agents/hosted/deploy.py). Empty until the hosted agent exists.')
param hostedAgentPrincipalId string = ''
param hostedAgentName string = 'voltrieve-hosted'
param chatModelName string = 'gpt-5.4-mini'
param chatModelVersion string = '2026-03-17'
param embeddingModelName string = 'text-embedding-3-large'
param embeddingModelVersion string = '1'

var placeholderImage = 'mcr.microsoft.com/dotnet/samples:aspnetapp'
var dealerName = 'ca-dealer-${environmentName}'
var apiName = 'ca-api-${environmentName}'
var docsContainer = 'voltrieve-docs'
var partsContainer = 'voltrieve-parts'
var token = toLower(uniqueString(subscription().id, environmentName, location))
var tags = { 'azd-env-name': environmentName, app: 'voltrieve' }

var storageBlobDataReader = '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
var cognitiveServicesOpenAIUser = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
var cognitiveServicesUser = 'a97b65f3-24c7-4388-baec-2e87135dc908'
var foundryProjectManager = 'eadc314b-1a2d-4efa-be10-5d325db5065e'
var acrPull = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var containerRegistryRepositoryReader = 'b93aa761-3e63-49ed-ac28-beffa264f7ac'
var searchIndexDataReader = '1407120a-92aa-4202-b7e9-c0e197c71c8f'
var searchServiceContributor = '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
var searchIndexDataContributor = '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
var storageBlobDataContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var foundryUser = '53ca6127-db72-4b80-b1b0-d745d6d5456d'

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-voltrieve-${environmentName}'
  location: location
  tags: tags
}

module monitoring 'modules/monitoring.bicep' = {
  scope: rg
  params: {
    name: 'voltrieve-${token}'
    location: location
    tags: tags
  }
}

module foundry 'modules/foundry.bicep' = {
  scope: rg
  params: {
    name: 'ai-voltrieve-${token}'
    location: location
    tags: tags
    projectName: 'voltrieve'
    appInsightsName: monitoring.outputs.appInsightsName
    chatModelName: chatModelName
    chatModelVersion: chatModelVersion
    embeddingModelName: embeddingModelName
    embeddingModelVersion: embeddingModelVersion
  }
}

module search 'modules/search.bicep' = {
  scope: rg
  params: {
    name: 'srch-voltrieve-${token}'
    location: searchLocation
    tags: tags
  }
}

module storage 'modules/storage.bicep' = {
  scope: rg
  params: {
    name: 'stvoltrieve${token}'
    location: location
    tags: tags
    docsContainer: docsContainer
    partsContainer: partsContainer
  }
}

module registry 'modules/registry.bicep' = {
  scope: rg
  params: {
    name: 'crvoltrieve${token}'
    location: location
    tags: tags
  }
}

module containerAppsEnv 'modules/containerapps-env.bicep' = {
  scope: rg
  params: {
    name: 'cae-voltrieve-${environmentName}'
    location: location
    tags: tags
    logAnalyticsName: monitoring.outputs.logAnalyticsName
  }
}

module dealerIdentity 'modules/app-identity.bicep' = {
  scope: rg
  params: {
    name: 'id-dealer-${environmentName}'
    location: location
    tags: tags
    registryName: registry.outputs.name
  }
}

module dealerCurrent 'modules/fetch-container-image.bicep' = if (dealerExists) {
  scope: rg
  params: {
    name: dealerName
  }
}

// dealerIdentity includes the AcrPull assignment, so depending on it orders the app after the grant.
module dealerApp 'modules/dealer-app.bicep' = {
  scope: rg
  params: {
    name: dealerName
    location: location
    tags: tags
    environmentId: containerAppsEnv.outputs.id
    registryLoginServer: registry.outputs.loginServer
    image: dealerExists ? dealerCurrent.?outputs.image ?? placeholderImage : placeholderImage
    pullIdentityId: dealerIdentity.outputs.id
    tenantId: tenantId
    dealerClientId: dealerClientId
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
  }
}

module apiIdentity 'modules/app-identity.bicep' = {
  scope: rg
  params: {
    name: 'id-api-${environmentName}'
    location: location
    tags: tags
    registryName: registry.outputs.name
  }
}

module apiCurrent 'modules/fetch-container-image.bicep' = if (apiExists) {
  scope: rg
  params: {
    name: apiName
  }
}

module web 'modules/static-web-app.bicep' = {
  scope: rg
  params: {
    name: 'stapp-voltrieve-${environmentName}'
    location: webLocation
    tags: tags
  }
}

module apiApp 'modules/api-app.bicep' = {
  scope: rg
  params: {
    name: apiName
    location: location
    tags: tags
    environmentId: containerAppsEnv.outputs.id
    registryLoginServer: registry.outputs.loginServer
    image: apiExists ? apiCurrent.?outputs.image ?? placeholderImage : placeholderImage
    pullIdentityId: apiIdentity.outputs.id
    tenantId: tenantId
    apiClientId: apiClientId
    dealerUrl: dealerApp.outputs.url
    dealerClientId: dealerClientId
    foundryProjectEndpoint: foundry.outputs.projectEndpoint
    chatDeployment: foundry.outputs.chatDeployment
    searchEndpoint: search.outputs.endpoint
    promptAgentCli: 'voltrieve-prompt-cli'
    promptAgentWeb: 'voltrieve-prompt-web'
    hostedAgentName: hostedAgentName
    corsOrigins: '${web.outputs.url},http://localhost:5173'
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
  }
}

// The API calls Foundry (agents and chat) and reads the search index with its own identity.
module apiUsesFoundry 'modules/role-foundry.bicep' = {
  scope: rg
  params: {
    resourceName: foundry.outputs.name
    principalId: apiApp.outputs.principalId
    roleDefinitionId: foundryUser
    principalType: 'ServicePrincipal'
  }
}

module apiReadsSearch 'modules/role-search.bicep' = {
  scope: rg
  params: {
    resourceName: search.outputs.name
    principalId: apiApp.outputs.principalId
    roleDefinitionId: searchIndexDataReader
    principalType: 'ServicePrincipal'
  }
}

// The hosted agent has its own identity and the same data-plane access as the API: it calls
// the model and reads the index itself. Dealer.Access comes from scripts/deploy-agents.sh.
module hostedUsesFoundry 'modules/role-foundry.bicep' = if (!empty(hostedAgentPrincipalId)) {
  scope: rg
  params: {
    resourceName: foundry.outputs.name
    principalId: hostedAgentPrincipalId
    roleDefinitionId: foundryUser
    principalType: 'ServicePrincipal'
  }
}

module hostedReadsSearch 'modules/role-search.bicep' = if (!empty(hostedAgentPrincipalId)) {
  scope: rg
  params: {
    resourceName: search.outputs.name
    principalId: hostedAgentPrincipalId
    roleDefinitionId: searchIndexDataReader
    principalType: 'ServicePrincipal'
  }
}

// Role assignments are declared on the target resource (least privilege).
module searchReadsStorage 'modules/role-storage.bicep' = {
  scope: rg
  params: {
    resourceName: storage.outputs.name
    principalId: search.outputs.principalId
    roleDefinitionId: storageBlobDataReader
    principalType: 'ServicePrincipal'
  }
}

module searchUsesFoundry 'modules/role-foundry.bicep' = {
  scope: rg
  params: {
    resourceName: foundry.outputs.name
    principalId: search.outputs.principalId
    roleDefinitionId: cognitiveServicesOpenAIUser
    principalType: 'ServicePrincipal'
  }
}

// The knowledge base calls the chat model for query planning, which needs this role.
module searchPlansWithFoundry 'modules/role-foundry.bicep' = {
  scope: rg
  params: {
    resourceName: foundry.outputs.name
    principalId: search.outputs.principalId
    roleDefinitionId: cognitiveServicesUser
    principalType: 'ServicePrincipal'
  }
}

// The project identity calls the knowledge base MCP endpoint for prompt agents.
module projectReadsSearch 'modules/role-search.bicep' = {
  scope: rg
  params: {
    resourceName: search.outputs.name
    principalId: foundry.outputs.projectPrincipalId
    roleDefinitionId: searchIndexDataReader
    principalType: 'ServicePrincipal'
  }
}

// The project identity pulls hosted agent images. AcrPull covers a registry in legacy
// permission mode, Repository Reader covers one using repository permissions.
module projectPullsImages 'modules/role-registry.bicep' = {
  scope: rg
  params: {
    resourceName: registry.outputs.name
    principalId: foundry.outputs.projectPrincipalId
    roleDefinitionId: acrPull
    principalType: 'ServicePrincipal'
  }
}

module projectReadsRepositories 'modules/role-registry.bicep' = {
  scope: rg
  params: {
    resourceName: registry.outputs.name
    principalId: foundry.outputs.projectPrincipalId
    roleDefinitionId: containerRegistryRepositoryReader
    principalType: 'ServicePrincipal'
  }
}

module kbConnection 'modules/foundry-kb-connection.bicep' = {
  scope: rg
  params: {
    accountName: foundry.outputs.name
    projectName: foundry.outputs.projectName
    searchEndpoint: search.outputs.endpoint
    knowledgeBaseName: 'voltrieve-kb'
  }
}

module partsKbConnection 'modules/foundry-kb-connection.bicep' = {
  scope: rg
  params: {
    accountName: foundry.outputs.name
    projectName: foundry.outputs.projectName
    searchEndpoint: search.outputs.endpoint
    knowledgeBaseName: 'voltrieve-parts-kb'
    connectionName: 'voltrieve-parts-kb-mcp'
  }
}

// Creating agents and project connections needs this role on the deployer.
module deployerManagesProject 'modules/role-foundry.bicep' = if (!empty(principalId)) {
  scope: rg
  params: {
    resourceName: foundry.outputs.name
    principalId: principalId
    roleDefinitionId: foundryProjectManager
    principalType: 'User'
  }
}

module deployerSearchService 'modules/role-search.bicep' = if (!empty(principalId)) {
  scope: rg
  params: {
    resourceName: search.outputs.name
    principalId: principalId
    roleDefinitionId: searchServiceContributor
    principalType: 'User'
  }
}

module deployerSearchData 'modules/role-search.bicep' = if (!empty(principalId)) {
  scope: rg
  params: {
    resourceName: search.outputs.name
    principalId: principalId
    roleDefinitionId: searchIndexDataContributor
    principalType: 'User'
  }
}

module deployerStorage 'modules/role-storage.bicep' = if (!empty(principalId)) {
  scope: rg
  params: {
    resourceName: storage.outputs.name
    principalId: principalId
    roleDefinitionId: storageBlobDataContributor
    principalType: 'User'
  }
}

module deployerFoundry 'modules/role-foundry.bicep' = if (!empty(principalId)) {
  scope: rg
  params: {
    resourceName: foundry.outputs.name
    principalId: principalId
    roleDefinitionId: foundryUser
    principalType: 'User'
  }
}

output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_LOCATION string = location
output DEPLOYER_PRINCIPAL_ID string = principalId
output FOUNDRY_ACCOUNT_NAME string = foundry.outputs.name
output FOUNDRY_ENDPOINT string = foundry.outputs.endpoint
output FOUNDRY_PROJECT_ENDPOINT string = foundry.outputs.projectEndpoint
output FOUNDRY_OPENAI_ENDPOINT string = foundry.outputs.openAiEndpoint
output CHAT_DEPLOYMENT string = foundry.outputs.chatDeployment
output CHAT_MODEL string = chatModelName
output FOUNDRY_PROJECT_NAME string = foundry.outputs.projectName
output KB_CONNECTION_NAME string = kbConnection.outputs.name
output PARTS_KB_CONNECTION_NAME string = partsKbConnection.outputs.name
output EMBEDDING_DEPLOYMENT string = foundry.outputs.embeddingDeployment
output EMBEDDING_MODEL string = embeddingModelName
output SEARCH_ENDPOINT string = search.outputs.endpoint
output SEARCH_SERVICE_NAME string = search.outputs.name
output STORAGE_ACCOUNT_NAME string = storage.outputs.name
output STORAGE_RESOURCE_ID string = storage.outputs.id
output DOCS_CONTAINER string = storage.outputs.docsContainer
output PARTS_CONTAINER string = storage.outputs.partsContainer
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = registry.outputs.loginServer
output AZURE_CONTAINER_REGISTRY_NAME string = registry.outputs.name
output CONTAINER_APPS_ENVIRONMENT_ID string = containerAppsEnv.outputs.id
output APPLICATIONINSIGHTS_CONNECTION_STRING string = monitoring.outputs.appInsightsConnectionString
output DEALER_URL string = dealerApp.outputs.url
output DEALER_PRINCIPAL_ID string = dealerApp.outputs.principalId
output HOSTED_AGENT_NAME string = hostedAgentName
output API_URL string = apiApp.outputs.url
output API_PRINCIPAL_ID string = apiApp.outputs.principalId
output WEB_URL string = web.outputs.url
