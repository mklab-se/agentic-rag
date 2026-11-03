targetScope = 'subscription'

@minLength(1)
@maxLength(22)
@description('Name of the azd environment, used in resource names and tags.')
param environmentName string

@description('Primary Azure region.')
param location string = 'swedencentral'

@description('Object id of the deployer (AZURE_PRINCIPAL_ID), granted data-plane roles.')
param principalId string

param tenantId string
param dealerClientId string
@description('True when the dealer Container App already exists (azd sets SERVICE_DEALER_RESOURCE_EXISTS), so provision keeps its deployed image.')
param dealerExists bool = false
param chatModelName string = 'gpt-5.4-mini'
param chatModelVersion string = '2026-03-17'
param embeddingModelName string = 'text-embedding-3-large'
param embeddingModelVersion string = '1'

var placeholderImage = 'mcr.microsoft.com/dotnet/samples:aspnetapp'
var dealerName = 'ca-dealer-${environmentName}'
var docsContainer = 'voltrieve-docs'
var token = toLower(uniqueString(subscription().id, environmentName, location))
var tags = { 'azd-env-name': environmentName, app: 'voltrieve' }

var storageBlobDataReader = '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
var cognitiveServicesOpenAIUser = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
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
    location: location
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
output FOUNDRY_ACCOUNT_NAME string = foundry.outputs.name
output FOUNDRY_ENDPOINT string = foundry.outputs.endpoint
output FOUNDRY_PROJECT_ENDPOINT string = foundry.outputs.projectEndpoint
output CHAT_DEPLOYMENT string = foundry.outputs.chatDeployment
output EMBEDDING_DEPLOYMENT string = foundry.outputs.embeddingDeployment
output EMBEDDING_MODEL string = embeddingModelName
output SEARCH_ENDPOINT string = search.outputs.endpoint
output SEARCH_SERVICE_NAME string = search.outputs.name
output STORAGE_ACCOUNT_NAME string = storage.outputs.name
output STORAGE_RESOURCE_ID string = storage.outputs.id
output DOCS_CONTAINER string = storage.outputs.docsContainer
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = registry.outputs.loginServer
output AZURE_CONTAINER_REGISTRY_NAME string = registry.outputs.name
output CONTAINER_APPS_ENVIRONMENT_ID string = containerAppsEnv.outputs.id
output APPLICATIONINSIGHTS_CONNECTION_STRING string = monitoring.outputs.appInsightsConnectionString
output DEALER_URL string = dealerApp.outputs.url
output DEALER_PRINCIPAL_ID string = dealerApp.outputs.principalId
