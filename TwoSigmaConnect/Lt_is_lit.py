# based on https://www.kaggle.com/rakhlin/two-sigma-connect-rental-listing-inquiries/another-python-version-of-it-is-lit-by-branden/code

import numpy as np
import pandas as pd
from sklearn.preprocessing import MultiLabelBinarizer
from itertools import product
from sklearn.model_selection import StratifiedKFold
import datetime as dt
import random


def add_features(df):
    fmt = lambda s: s.replace("\u00a0", "").strip().lower()
    df["photo_count"] = df["photos"].apply(len)
    df["street_address"] = df['street_address'].apply(fmt)
    df["display_address"] = df["display_address"].apply(fmt)
    df["desc_wordcount"] = df["description"].apply(len)
    df["pricePerBed"] = df['price'] / df['bedrooms']
    df["pricePerBath"] = df['price'] / df['bathrooms']
    df["pricePerRoom"] = df['price'] / (df['bedrooms'] + df['bathrooms'])
    df["bedPerBath"] = df['bedrooms'] / df['bathrooms']
    df["bedBathDiff"] = df['bedrooms'] - df['bathrooms']
    df["bedBathSum"] = df["bedrooms"] + df['bathrooms']
    df["bedsPerc"] = df["bedrooms"] / (df['bedrooms'] + df['bathrooms'])

    # added from another script
    df["created"] = pd.to_datetime(df["created"])
    df["created_year"] = df["created"].dt.year
    df["created_month"] = df["created"].dt.month
    df["created_day"] = df["created"].dt.day
    df["created_hour"] = df["created"].dt.hour
    df['created_weekday'] = df['created'].dt.weekday
    df['created_week'] = df['created'].dt.week
    df['created_quarter'] = df['created'].dt.quarter
    # df['created_weekend'] = ((df['created_weekday'] == 5) & (df['created_weekday'] == 6))
    # df['created_wd'] = ((df['created_weekday'] != 5) & (df['created_weekday'] != 6))
    # df['created'] = df['created'].map(lambda x: float((x - dt.datetime(1899, 12, 30)).days) + (float((x - dt.datetime(1899, 12, 30)).seconds) / 86400))

    df = df.fillna(-1).replace(np.inf, -1)
    return df


def factorize(df1, df2, column):
    ps = df1[column].append(df2[column])
    factors = ps.factorize()[0]
    df1[column] = factors[:len(df1)]
    df2[column] = factors[len(df1):]
    return df1, df2


def designate_single_observations(df1, df2, column):
    ps = df1[column].append(df2[column])
    grouped = ps.groupby(ps).size().to_frame().rename(columns={0: "size"})
    df1.loc[df1.join(grouped, on=column, how="left")["size"] <= 1, column] = -1
    df2.loc[df2.join(grouped, on=column, how="left")["size"] <= 1, column] = -1
    return df1, df2


def hcc_encode(train_df, test_df, variable, target, prior_prob, k, f=1, g=1, r_k=None, update_df=None):
    """
    See "A Preprocessing Scheme for High-Cardinality Categorical Attributes in
    Classification and Prediction Problems" by Daniele Micci-Barreca
    """
    hcc_name = "_".join(["hcc", variable, target])

    grouped = train_df.groupby(variable)[target].agg({"size": "size", "mean": "mean"})
    grouped["lambda"] = 1 / (g + np.exp((k - grouped["size"]) / f))
    grouped[hcc_name] = grouped["lambda"] * grouped["mean"] + (1 - grouped["lambda"]) * prior_prob

    df = test_df[[variable]].join(grouped, on=variable, how="left")[hcc_name].fillna(prior_prob)
    if r_k: df *= np.random.uniform(1 - r_k, 1 + r_k, len(test_df))     # Add uniform noise. Not mentioned in original paper

    if update_df is None: update_df = test_df
    if hcc_name not in update_df.columns: update_df[hcc_name] = np.nan
    update_df.update(df)
    return


def add_manager_skill(train_df, test_df):
    # added from another script
    # add manager_skill feature (pozor na leak)
    y_train = train_df["interest_level"]
    # compute fractions and count for each manager
    temp = pd.concat([train_df.manager_id,pd.get_dummies(y_train)], axis = 1).groupby('manager_id').mean()
    print(temp.columns)
    temp.columns = ['high_frac','low_frac', 'medium_frac']
    temp['count'] = train_df.groupby('manager_id').count().iloc[:,1]

    # remember the manager_ids look different because we encoded them in the previous step 
    print(temp.tail(10))

    # compute skill
    temp['manager_skill'] = temp['high_frac']*2 + temp['medium_frac']

    # get ixes for unranked managers...
    unranked_managers_ixes = temp['count']<20
    # ... and ranked ones
    ranked_managers_ixes = ~unranked_managers_ixes

    # compute mean values from ranked managers and assign them to unranked ones
    mean_values = temp.loc[ranked_managers_ixes, ['high_frac','low_frac', 'medium_frac','manager_skill']].mean()
    print(mean_values)
    temp.loc[unranked_managers_ixes,['high_frac','low_frac', 'medium_frac','manager_skill']] = mean_values.values
    print(temp.tail(10))

    # inner join to assign manager features to the managers in the training dataframe
    train_df = train_df.merge(temp.reset_index(),how='left', left_on='manager_id', right_on='manager_id')
    print(train_df.head())

    # add the features computed on the training dataset to the test dataset
    test_df = test_df.merge(temp.reset_index(),how='left', left_on='manager_id', right_on='manager_id')
    new_manager_ixes = test_df['high_frac'].isnull()
    test_df.loc[new_manager_ixes,['high_frac','low_frac', 'medium_frac','manager_skill']] = mean_values.values
    return train_df, test_df


def add_manager_level_weaker_leakage(train_df, test_df):
    index=list(range(train_df.shape[0]))
    random.shuffle(index)
    a=[np.nan]*len(train_df)
    b=[np.nan]*len(train_df)
    c=[np.nan]*len(train_df)

    for i in range(5):
        building_level={}
        for j in train_df['manager_id'].values:
            building_level[j]=[0,0,0]
        test_index=index[int((i*train_df.shape[0])/5):int(((i+1)*train_df.shape[0])/5)]
        train_index=list(set(index).difference(test_index))
        for j in train_index:
            temp=train_df.iloc[j]
            if temp['interest_level']=='low':
                building_level[temp['manager_id']][0]+=1
            if temp['interest_level']=='medium':
                building_level[temp['manager_id']][1]+=1
            if temp['interest_level']=='high':
                building_level[temp['manager_id']][2]+=1
        for j in test_index:
            temp=train_df.iloc[j]
            if sum(building_level[temp['manager_id']])!=0:
                a[j]=building_level[temp['manager_id']][0]*1.0/sum(building_level[temp['manager_id']])
                b[j]=building_level[temp['manager_id']][1]*1.0/sum(building_level[temp['manager_id']])
                c[j]=building_level[temp['manager_id']][2]*1.0/sum(building_level[temp['manager_id']])
    train_df['manager_level_low']=a
    train_df['manager_level_medium']=b
    train_df['manager_level_high']=c


    a=[]
    b=[]
    c=[]
    building_level={}
    for j in train_df['manager_id'].values:
        building_level[j]=[0,0,0]
    for j in range(train_df.shape[0]):
        temp=train_df.iloc[j]
        if temp['interest_level']=='low':
            building_level[temp['manager_id']][0]+=1
        if temp['interest_level']=='medium':
            building_level[temp['manager_id']][1]+=1
        if temp['interest_level']=='high':
            building_level[temp['manager_id']][2]+=1

    for i in test_df['manager_id'].values:
        if i not in building_level.keys():
            a.append(np.nan)
            b.append(np.nan)
            c.append(np.nan)
        else:
            a.append(building_level[i][0]*1.0/sum(building_level[i]))
            b.append(building_level[i][1]*1.0/sum(building_level[i]))
            c.append(building_level[i][2]*1.0/sum(building_level[i]))
    test_df['manager_level_low']=a
    test_df['manager_level_medium']=b
    test_df['manager_level_high']=c
    return train_df, test_df



# Load data
X_train = pd.read_json("input/train.json").sort_values(by="listing_id")
X_test = pd.read_json("input/test.json").sort_values(by="listing_id")

# add manager skill
# X_train, X_test = add_manager_skill(X_train, X_test) # not good; big leakage
# X_train, X_test = add_manager_level_weaker_leakage(X_train, X_test)

# Make target integer, one hot encoded, calculate target priors
X_train = X_train.replace({"interest_level": {"low": 0, "medium": 1, "high": 2}})
X_train = X_train.join(pd.get_dummies(X_train["interest_level"], prefix="pred").astype(int))
prior_0, prior_1, prior_2 = X_train[["pred_0", "pred_1", "pred_2"]].mean()

# Add common features
X_train = add_features(X_train)
X_test = add_features(X_test)

# Special designation for building_ids, manager_ids, display_address with only 1 observation
for col in ('building_id', 'manager_id', 'display_address'):
    X_train, X_test = designate_single_observations(X_train, X_test, col)

# High-Cardinality Categorical encoding
skf = StratifiedKFold(5)
attributes = product(("building_id", "manager_id"), zip(("pred_1", "pred_2"), (prior_1, prior_2)))
for variable, (target, prior) in attributes:
    hcc_encode(X_train, X_test, variable, target, prior, k=5, r_k=None)
    for train, test in skf.split(np.zeros(len(X_train)), X_train['interest_level']):
        hcc_encode(X_train.iloc[train], X_train.iloc[test], variable, target, prior, k=5, r_k=0.01, update_df=X_train)

# Factorize building_id, display_address, manager_id, street_address
for col in ('building_id', 'display_address', 'manager_id', 'street_address'):
    X_train, X_test = factorize(X_train, X_test, col)

# Create binarized features
fmt = lambda feat: [s.replace("\u00a0", "").strip().lower().replace(" ", "_") for s in feat]  # format features
X_train["features"] = X_train["features"].apply(fmt)
X_test["features"] = X_test["features"].apply(fmt)
features = [f for f_list in list(X_train["features"]) + list(X_test["features"]) for f in f_list]
ps = pd.Series(features)
grouped = ps.groupby(ps).agg(len)
features = grouped[grouped >= 10].index.sort_values().values    # limit to features with >=10 observations
mlb = MultiLabelBinarizer().fit([features])
columns = ['feature_' + s for s in mlb.classes_]
flt = lambda l: [i for i in l if i in mlb.classes_]     # filter out features not present in MultiLabelBinarizer
X_train = X_train.join(pd.DataFrame(data=mlb.transform(X_train["features"].apply(flt)), columns=columns, index=X_train.index))
X_test = X_test.join(pd.DataFrame(data=mlb.transform(X_test["features"].apply(flt)), columns=columns, index=X_test.index))







# Save

X_train = X_train.sort_index(axis=1).sort_values(by="listing_id")
X_test = X_test.sort_index(axis=1).sort_values(by="listing_id")
columns_to_drop = ["photos", "pred_0","pred_1", "pred_2", "description", "features", "created"]
X_train.drop([c for c in X_train.columns if c in columns_to_drop], axis=1).\
    to_csv("data_prepared/train_Man.csv", index=False, encoding='utf-8')
X_test.drop([c for c in X_test.columns if c in columns_to_drop], axis=1).\
    to_csv("data_prepared/test_Man.csv", index=False, encoding='utf-8')
 