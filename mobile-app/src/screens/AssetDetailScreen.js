import React from 'react';
import { View, StyleSheet, ScrollView } from 'react-native';
import { Card, Title, Paragraph, Chip, List, Divider } from 'react-native-paper';
import { useQuery, gql } from '@apollo/client';

const ASSET_DETAIL_QUERY = gql`
  query AssetDetail($id: ID!) {
    asset(id: $id) {
      id
      name
      assetType
      manufacturer
      model
      serialNumber
      status
      purchaseDate
      warrantyExpiry
      notes
      location
      rack
      rackPosition
      organization {
        name
      }
    }
  }
`;

export default function AssetDetailScreen({ route }) {
  const { assetId } = route.params;
  const { data, loading } = useQuery(ASSET_DETAIL_QUERY, {
    variables: { id: assetId },
  });

  const asset = data?.asset;

  if (loading) {
    return (
      <View style={styles.container}>
        <Paragraph style={styles.loadingText}>Loading...</Paragraph>
      </View>
    );
  }

  if (!asset) {
    return (
      <View style={styles.container}>
        <Paragraph style={styles.errorText}>Asset not found</Paragraph>
      </View>
    );
  }

  return (
    <ScrollView style={styles.container}>
      <Card style={styles.card}>
        <Card.Title
          title={asset.name}
          subtitle={asset.organization?.name}
        />
        <Card.Content>
          <View style={styles.statusRow}>
            <Chip mode="outlined" style={styles.chip}>
              {asset.assetType}
            </Chip>
            <Chip mode="flat" style={styles.statusChip}>
              {asset.status}
            </Chip>
          </View>
        </Card.Content>
      </Card>

      <Card style={styles.card}>
        <Card.Title title="Details" />
        <Card.Content>
          <List.Item
            title="Manufacturer"
            description={asset.manufacturer || 'N/A'}
            left={(props) => <List.Icon {...props} icon="factory" />}
          />
          <Divider />
          <List.Item
            title="Model"
            description={asset.model || 'N/A'}
            left={(props) => <List.Icon {...props} icon="barcode" />}
          />
          <Divider />
          <List.Item
            title="Serial Number"
            description={asset.serialNumber || 'N/A'}
            left={(props) => <List.Icon {...props} icon="identifier" />}
          />
        </Card.Content>
      </Card>

      <Card style={styles.card}>
        <Card.Title title="Location" />
        <Card.Content>
          <List.Item
            title="Location"
            description={asset.location || 'N/A'}
            left={(props) => <List.Icon {...props} icon="map-marker" />}
          />
          {asset.rack && (
            <>
              <Divider />
              <List.Item
                title="Rack"
                description={`${asset.rack} - Position ${asset.rackPosition || 'N/A'}`}
                left={(props) => <List.Icon {...props} icon="server" />}
              />
            </>
          )}
        </Card.Content>
      </Card>

      {asset.notes && (
        <Card style={styles.card}>
          <Card.Title title="Notes" />
          <Card.Content>
            <Paragraph>{asset.notes}</Paragraph>
          </Card.Content>
        </Card>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0d1117',
  },
  card: {
    margin: 12,
    backgroundColor: '#161b22',
  },
  statusRow: {
    flexDirection: 'row',
    marginTop: 8,
    gap: 8,
  },
  chip: {
    borderColor: '#0d6efd',
  },
  statusChip: {
    backgroundColor: '#28a745',
  },
  loadingText: {
    textAlign: 'center',
    marginTop: 40,
    color: '#8b949e',
  },
  errorText: {
    textAlign: 'center',
    marginTop: 40,
    color: '#dc3545',
  },
});
