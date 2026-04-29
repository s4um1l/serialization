@0xdbb9ad1f14bf0b36;  # unique file ID

struct GeoPoint {
  latitude @0 :Float64;
  longitude @1 :Float64;
}

enum OrderStatus {
  placed @0;
  confirmed @1;
  preparing @2;
  ready @3;
  pickedUp @4;
  enRoute @5;
  delivered @6;
  cancelled @7;
}

enum PaymentMethod {
  creditCard @0;
  debitCard @1;
  cash @2;
  wallet @3;
}

struct MenuItem {
  id @0 :Text;
  name @1 :Text;
  priceCents @2 :Int32;
  description @3 :Text;
  category @4 :Text;
  isVegetarian @5 :Bool;
  allergens @6 :List(Text);
  thumbnailPng @7 :Data;
}

struct OrderItem {
  menuItem @0 :MenuItem;
  quantity @1 :Int32;
  specialInstructions @2 :Text;
}

struct Customer {
  id @0 :Text;
  name @1 :Text;
  email @2 :Text;
  phone @3 :Text;
  address @4 :Text;
  location @5 :GeoPoint;
}

struct Order {
  id @0 :Text;
  platformTransactionId @1 :Int64;
  customer @2 :Customer;
  restaurantId @3 :Text;
  items @4 :List(OrderItem);
  status @5 :OrderStatus;
  paymentMethod @6 :PaymentMethod;
  driverId @7 :Text;
  deliveryNotes @8 :Text;
  promoCode @9 :Text;
  tipCents @10 :Int32;
  createdAt @11 :Float64;
  updatedAt @12 :Float64;
  estimatedDeliveryMinutes @13 :Int32;
}
